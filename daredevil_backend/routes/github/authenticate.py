import asyncio
import time
from typing import List

import logfire
from fastapi import APIRouter, HTTPException, WebSocket
from httpx import AsyncClient, HTTPStatusError
from rich import inspect, print
from sqlmodel import select

from ...configs import GithubAppLib
from ...dbs import get_async_session
from ...models import (App, AppResponse, AppTokenResponse,
                       OAuthAccessTokenResponse, User, UserResponse)

api = APIRouter(prefix="/github")


# class ApiError(SQLModel):
#     status_code: Literal[401, 403, 404, 422]


class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def send_update(self, msg: str, websocket: WebSocket):
        await websocket.send_text(msg)

    async def broadcast(self, msg: str):
        for connection in self.active_connections:
            await connection.send_text(msg)


manager = ConnectionManager()
# url = f"https://api.github.com/users/{username}/installation"
# u.model_dump_json(exclude=set("password")


@api.get("/get-app")
async def get_app(*, app_slug: str, client_id: str) -> App:
    """This GET request searches Github Api looking for App with 'app_slug'"""
    """I found out late one night this route also needs a JWT from a key..."""

    gha_lib = GithubAppLib()
    app_jwt = gha_lib.create_jwt(client_id=client_id)

    url = f"https://api.github.com/apps?{app_slug}"
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Authorization": f"Bearer {app_jwt}",
        "User-Agent": "daredevil-deployer",
    }
    try:
        async with AsyncClient() as viper:
            response = await viper.get(url=url, headers=headers)
            data = response.json()
            github_app_obj = AppResponse.model_validate(data)

            session = await get_async_session()
            async with session:
                statement = select(App).where(
                    App.github_app_id == github_app_obj.id
                )
                github_app = (await session.exec(statement)).one_or_none()
                if github_app is None:
                    gha_id = github_app_obj.id
                    app_dict = App.model_dump(github_app_obj)
                    del app_dict["id"]
                    app_dict["github_app_id"] = gha_id
                    app_obj = App.model_validate(app_dict)
                    session.add(app_obj)
                    await session.commit()
                    await session.refresh(app_obj)

    except Exception as e:
        logfire.error(f"GitHub App Ids Get Error: {e.msg}")
        raise Exception(f"Error: {e.msg}")
    finally:
        logfire.info("GitHub App Validated & Stored in DB")
        inspect(app_obj)
        return app_obj


# Authenticate as a GitHub App
@api.post("/authenticate-as-app")
async def authenticate_as_app(*, gha_id: str) -> AppTokenResponse:
    session = await get_async_session()
    async with session:
        statement = select(App).where(App.github_app_id == gha_id)
        g_app = (await session.exec(statement)).one_or_none()
        if g_app is None:
            return {"status_code": 404, "message": "Not Found."}

    app_jwt = GithubAppLib.create_jwt(g_app.client_id)

    url = f"https://api.github.com/app/installations/{g_app.github_app_id}/access_tokens"
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Authorization": f"Bearer {app_jwt}",
        "User-Agent": "daredevil-deployer",
    }

    try:
        async with AsyncClient() as viper:
            response = await viper.post(url=url, headers=headers)
            inspect(response.json())
            gh_app_token_obj = AppTokenResponse.model_validate(response.json())
            inspect(gh_app_token_obj)

        return gh_app_token_obj
    except Exception as e:
        logfire.error(f"GHA Installation Get Error: {e.status_code}")
        raise Exception(f"Error: {e.status_code}")


@api.websocket("/poll-create-token/{id}")
async def poll_create_token(*, id: str, websocket: WebSocket):
    await manager.connect(websocket)
    session = await get_async_session()
    async with session:
        statement = select(User).where(User.id == id)
        user = (await session.exec(statement)).one_or_none()
        inspect(user)
    interval = user.interval or 15
    logfire.info(f"Starting polling with interval: {interval} seconds")

    while True:
        token_link = "https://github.com/login/oauth/access_token"
        header = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "daredevil-token-depot",
        }
        grant_type = "urn:ietf:params:oauth:grant-type:device_code"

        logfire.info("polling user access token with code ...")
        await manager.send_update(
            f"polling user access token at github (waiting {interval}s) ...",
            websocket,
        )
        start_time = time.time()
        try:
            while time.time() - start_time < user.expires_in:
                # Wait for the interval before polling
                logfire.info(f"Waiting {interval}s before next poll...")
                await asyncio.sleep(interval)

                async with AsyncClient() as viper:
                    response = await viper.post(
                        url=token_link,
                        headers=header,
                        data={
                            "client_id": user.client_id,
                            "device_code": user.device_code,
                            "grant_type": grant_type,
                        },
                    )

                    oauth_response = response.json()
                    logfire.info(f"GitHub response: {oauth_response}")

                    if "access_token" in oauth_response:
                        oa_atr_model = OAuthAccessTokenResponse.model_validate(
                            oauth_response
                        )
                        logfire.info("GH user access token collected")
                        await manager.send_update(
                            f"OAuth token retrieved: {oa_atr_model.access_token}",
                            websocket,
                        )
                        async with session:
                            user.access_token = oa_atr_model.access_token
                            session.add(user)
                            await session.commit()
                            await session.refresh(user)
                            print(user)

                        manager.disconnect(websocket)
                        inspect(user)
                        break
                    elif "error" in oauth_response:
                        error = oauth_response.get("error")
                        match error:
                            case "authorization_pending":
                                logfire.info("Authorization is Pending")
                                await manager.send_update(
                                    "Authorization is Pending", websocket
                                )
                            case "slow_down":
                                interval += 10
                                logfire.info(
                                    f"authorization slow down - increasing interval to {interval}s"
                                )
                                await manager.send_update(
                                    f"Authorization Slow Down - waiting {interval}s",
                                    websocket,
                                )
                            case "incorrect_device_code":
                                logfire.info(
                                    "Incorrect Device Code, Try Again."
                                )
                                await manager.send_update(
                                    "Incorrect Device Code, Try Again.",
                                    websocket,
                                )
                            case _:
                                if error in [
                                    "expired_token",
                                    "access_denied",
                                    "device_flow_disabled",
                                    "unsupported_grant_type",
                                    "incorrect_client_credentials",
                                ]:
                                    raise Exception(error)
                        continue

        except Exception as e:
            logfire.error(f"GitHub OAuth Polling Error: {e.msg}")
            await manager.send_update(
                f"GitHub OAuth Polling Error: {e.msg}", websocket
            )
            manager.disconnect(websocket)
            raise Exception(f"Error: {e.msg}")
        finally:
            logfire.info("GitHub OAuth polling closed")
            await manager.send_update("GitHub OAuth polling closed.", websocket)
            manager.disconnect(websocket)


# Github App Installation Token
@api.post("/create-installation-token")
async def create_installation_token(*, client_id: str) -> AppTokenResponse:
    """This endpoint locates the installation of the github app by"""
    """ an installation id. The request needs a jwt with the app's client id."""
    """"""

    gha_lib = GithubAppLib()
    app_jwt = gha_lib.create_jwt(client_id=client_id)

    header = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Authorization": f"Bearer {app_jwt}",
    }
    organ = "the-woodford-den"

    url = f"https://api.github.com/orgs/{organ}/installation"
    async with AsyncClient() as client:
        response = await client.get(url=url, headers=header)
        data = response.json()
        inspect(data)

    endpoint = (
        f"https://api.github.com/app/installations/{data['id']}/access_tokens"
    )

    with logfire.span("Sending Request from create_installation_token() ..."):
        try:
            async with AsyncClient() as client:
                response = await client.post(url=endpoint, headers=header)
                logfire.info(f"github token response: {response.json()}")
                inspect(response.json())

                response.raise_for_status()

                return response.json()
        except HTTPStatusError as e:
            logfire.error(f"HTTP Status Error: {e.response.status_code}")

            raise HTTPException(
                status_code=e.response.status_code,
                detail=f"GitHub API error: {e.response.text}",
            )
