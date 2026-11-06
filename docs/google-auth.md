# Google sign-in and account linking

Google sign-in extends the existing password authentication. It is optional and uses the OAuth 2.0 authorization-code flow with OpenID Connect. No Google access/refresh token is needed by the application after login, and none is retained. A successful callback issues the same AgentShield HttpOnly cookie and server-side session used by password login.

## Google Cloud setup

1. Create/select a Google Cloud project and configure Google Auth Platform's consent screen (branding, audience, developer contact). Select an audience appropriate to your project; add your Google account as a test user while the consent screen is in testing.
2. Create an OAuth client of type **Web application**. This does not require a paid authentication provider. Google policies and quotas still apply.
3. Register the exact authorized redirect URI `http://localhost:3000/api/auth/google/callback` for local development. The browser returns through Next.js, which proxies the callback to FastAPI. Use the same hostname/port throughout login; `localhost` and `127.0.0.1` are different cookie/origin hosts.
4. For an HTTPS deployment, register `https://YOUR_HOST/api/auth/google/callback` separately. Never use wildcard callbacks. If Google requests an authorized JavaScript origin, use your exact frontend origin; this application uses server-side code exchange rather than a browser token SDK.
5. Store all three settings in ignored `backend/.env` for native development or ignored `.env.compose` for Compose. Preserve existing application JWT/audit keys and database credentials:

```dotenv
GOOGLE_CLIENT_ID=YOUR_CLIENT_ID.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=YOUR_CLIENT_SECRET
GOOGLE_REDIRECT_URI=http://localhost:3000/api/auth/google/callback
```

These are placeholders, not usable credentials. Keep the populated file private. Leave all three empty to disable Google login; partial configuration is rejected. The callback origin must exactly match one of `CORS_ORIGINS`. Restart the native backend or recreate the Compose backend after configuration changes. Production requires `APP_ENV=production`, HTTPS/WSS and Secure cookies.

## Endpoints and security

- `GET /api/auth/providers`: public configuration availability, with no keys.
- `POST /api/auth/google/start`: CSRF-protected request with `{"mode":"login"}` or `{"mode":"link"}`. Link mode requires an authenticated account. Returns the fixed Google authorization URL.
- `GET /api/auth/google/callback`: validates the one-time browser-bound state and code response, performs PKCE exchange, verifies the signed Google identity, and redirects to a fixed application destination.

State is random, short-lived and atomically consumed; a browser-binding HttpOnly cookie protects against login CSRF. S256 PKCE and nonce are independent checks. Verification requires trusted Google signing keys, RS256, issuer, client audience, expiration and identity claims. Provider HTTP operations have fixed endpoints, bounds and timeouts. Client-supplied redirect destinations, identity claims and email-only identity assertions are not accepted.

A Google account is identified by its stable `sub`. Matching an existing password-account email never logs into or merges that account. Sign in with its password, open Profile, and choose **Connect Google**. The linking attempt must still belong to that live original session at callback time. An identity already linked to another user is rejected. Google-only users have no synthetic password; password login for such users returns the same generic invalid-credentials response as other failed logins.

The migration is additive: existing password hashes and account IDs remain intact, Google subjects get a unique partial index, and transient OAuth state gets a TTL index. Existing password accounts default to unverified email unless independently verified; signing in to Google does not silently replace an existing account's primary email. MongoDB must be available for state, identity and session changes; failures must not issue a successful session.

## Logging and deployment

Authorization codes, state, identity tokens and client secrets must never appear in logs. The supplied native/backend-container launchers disable HTTP access logs; application logging also sanitizes callback queries. Configure reverse proxies, CDNs and external request tracing to omit callback query strings. The application cannot sanitize logs written before a request reaches it. Do not record callback URLs or tokens in screenshots or support reports.

Keep database access private and protect the OAuth client secret like the JWT/audit keys. Google profile pictures are optional external images; loading them may disclose browser network information to Google's image service. No application server fetches arbitrary profile-picture URLs.

## Manual verification (requires your Google client)

1. Start MongoDB, backend and frontend with the exact configured origin. Open Register or Login and select **Continue with Google**.
2. Complete Google's genuine consent/account-selection flow. Verify Profile, session expiry, protected pages and logout.
3. Repeat sign-in with the same Google account and confirm the same account/history remains.
4. Test cancellation and denied consent; the application should show a safe error and no session.
5. Create a password account matching a Google email. Google login must report a conflict; it must not grant that password account's access. Sign in by password, explicitly link Google in Profile, then test Google login again.
6. Start linking, then log out before callback. Linking must fail. A replayed callback must fail, as must attempts to link a Google identity already attached to another user.

Automated tests use mocked Google HTTP responses with generated test signing keys and real disposable MongoDB. They verify protocol enforcement, not an actual Google account/consent configuration. Live Google login is **NOT VERIFIED** until this manual flow succeeds with operator-provided credentials and connectivity. Password recovery remains unimplemented; the UI provides an honest explanation rather than a nonfunctional reset promise.
