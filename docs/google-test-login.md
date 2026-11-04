# Gmail test sign-in

The app already uses OpenID Connect. A Google Cloud OAuth **Web application** client can supply the test issuer and credentials; no Google-specific SDK is needed. Use a separate test project and disposable attendance data. This is for named Gmail testers, not a school rollout.

1. In Google Cloud Console, configure the Google Auth Platform consent screen with **External** audience and **Testing** publishing status. Add each Gmail account under **Test users**.
2. Create an OAuth client of type **Web application**. Register the exact redirect URI `http://localhost:1234/auth/callback` for a local test, or `https://<staging-domain>/auth/callback` for an HTTPS staging host. The redirect must match `PUBLIC_BASE_URL` exactly, including scheme and port.
3. Set these values in the app's private environment file (for local Compose, `.env.docker`; for a staging deployment, its private env file):

   ```dotenv
   OIDC_METADATA_URL=https://accounts.google.com/.well-known/openid-configuration
   OIDC_CLIENT_ID=<Google Web client ID>
   OIDC_CLIENT_SECRET=<Google Web client secret>
   AUTH_SESSION_SECRET=<random secret of at least 32 characters>
   PUBLIC_BASE_URL=http://localhost:1234
   COOKIE_SECURE=false
   OIDC_REQUIRED_CLAIMS_JSON=
   ```

4. Start the app in the chosen test environment, visit `/login`, and sign in with a listed test user. The first sign-in creates a student account. To test the instructor UI, explicitly grant that account the instructor role using `python -m app.manage_user grant-instructor <email>` inside the app container, then sign out and back in.
5. Test a second listed account as a student. Verify that an unlisted Gmail account cannot authorize the app while the Google project remains in Testing mode. Do not put OAuth client secrets in Git or issue trackers.

When moving to Google Workspace, set `OIDC_REQUIRED_CLAIMS_JSON={"hd":"school.edu"}` (or an array of accepted Workspace domains) and use an HTTPS public URL with secure cookies. The app checks `hd` in the verified ID token before provisioning; an email ending in `@school.edu` alone is not proof of Workspace membership. Production startup rejects a Google issuer without an `hd` policy. For another school OIDC provider, set an appropriate trusted claim, such as `{"tid":"<tenant UUID>"}` for a Microsoft Entra tenant, and confirm the issuer is scoped to the school.

Google setup references: [OpenID Connect](https://developers.google.com/identity/openid-connect/openid-connect), [Web application OAuth client](https://developers.google.com/identity/protocols/oauth2/web-server), and [Testing audience](https://support.google.com/cloud/answer/15549945).
