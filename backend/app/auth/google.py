"""Google sign-in identity through OIDC UserInfo, without a People API dependency."""

from httpx_oauth.clients.google import GoogleOAuth2
from httpx_oauth.exceptions import GetIdEmailError

USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"


class GoogleOpenID(GoogleOAuth2):
    def __init__(self, client_id: str, client_secret: str):
        super().__init__(client_id, client_secret, scopes=["openid", "email", "profile"])

    async def get_id_email(self, token: str) -> tuple[str, str | None]:
        async with self.get_httpx_client() as client:
            response = await client.get(
                USERINFO_ENDPOINT,
                headers={**self.request_headers, "Authorization": f"Bearer {token}"},
            )
        if response.status_code != 200:
            raise GetIdEmailError(response=response)
        try:
            profile = response.json()
        except ValueError as exc:
            raise GetIdEmailError(response=response) from exc
        # Never identify accounts by mutable email or mark an unverified address verified.
        if (
            not isinstance(profile, dict)
            or not isinstance(profile.get("sub"), str)
            or not profile["sub"].strip()
            or not isinstance(profile.get("email"), str)
            or not profile["email"].strip()
            or profile.get("email_verified") is not True
        ):
            raise GetIdEmailError(response=response)
        return profile["sub"], profile["email"]
