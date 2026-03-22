# Releasing Werkzeugkasten

This project is set up for a signed and notarized GitHub release of the macOS app bundle. Python remains an external prerequisite in v1.

## 1. Finalize Apple identifiers and capabilities

1. Create or confirm these bundle identifiers in Apple Developer:
   - `com.morrisfrank.werkzeugkasten`
   - `com.morrisfrank.werkzeugkasten.action`
2. Create or confirm the shared App Group:
   - `group.com.morrisfrank.werkzeugkasten`
3. Enable Keychain Sharing and use this shared access-group suffix:
   - `com.morrisfrank.werkzeugkasten.shared`
4. Make sure the app target and the action extension target both include the App Group and Keychain Sharing capabilities in Xcode.
5. Add an actual `icon.icns` for the action extension before the public release if you want Finder preview UI to show a branded icon instead of the template fallback.

## 2. Prepare signing assets

1. Create or export a `Developer ID Application` certificate.
2. Export it as a `.p12` file with a password.
3. If your Apple entitlements require provisioning profiles for Developer ID distribution, export one for the app target and one for the action extension target.
4. Generate notarization credentials for CI:
   - Apple ID
   - app-specific password
   - Team ID

## 3. Add GitHub Actions secrets

Add these repository secrets:

- `APPLE_TEAM_ID`
- `APPLE_DEVELOPER_ID_APPLICATION_CERT_BASE64`
- `APPLE_DEVELOPER_ID_APPLICATION_CERT_PASSWORD`
- `APPLE_NOTARY_APPLE_ID`
- `APPLE_NOTARY_PASSWORD`
- `APPLE_NOTARY_TEAM_ID`

Optional provisioning-profile secrets:

- `APPLE_APP_PROVISIONING_PROFILE_BASE64`
- `APPLE_EXTENSION_PROVISIONING_PROFILE_BASE64`

The certificate and provisioning-profile secrets should contain raw base64 of the exported files.

## 4. Verify local release prerequisites

1. Install Python 3.11+ and make sure the interpreter path is valid in Settings.
2. Install Python dependencies:
   - `python3 -m pip install -r requirements.txt`
3. Regenerate the Xcode project:
   - `xcodegen generate`
4. Open the project once in Xcode and verify Signing & Capabilities for both targets.
5. Build a Release archive locally before tagging:
   - `xcodebuild -project Werkzeugkasten.xcodeproj -scheme Werkzeugkasten -configuration Release archive -archivePath build/Werkzeugkasten.xcarchive DEVELOPMENT_TEAM=<team-id>`

## 5. Publish a GitHub release

1. Commit the release changes.
2. Create and push a semantic version tag:
   - `git tag v0.1.0`
   - `git push origin v0.1.0`
3. GitHub Actions will:
   - regenerate the project
   - archive the app
   - zip the `.app`
   - notarize the zip
   - staple the app
   - publish the release asset and checksum

## 6. Verify the public artifact

1. Download the GitHub release zip on a second Mac or a clean user profile.
2. Unzip the app and confirm Gatekeeper accepts it.
3. Launch the app, set the Python interpreter in Settings, and save the API key.
4. Enable the Finder extension in System Settings > Privacy & Security > Extensions.
5. Confirm:
   - menu-bar windows open centered and in front
   - `Summarize` works from the app
   - the Finder action appears and can summarize files
   - `Prettify Codex Log` writes `<name>.jsonl.transcript.md`
