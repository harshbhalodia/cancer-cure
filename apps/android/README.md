# AshaDeep (આશાદીપ) Android app

| What to change | Where |
|---|---|
| Hospital brand, app name, tagline | `assets/config.js` → `brand` |
| Language (gu / en, add more) | `assets/config.js` → `lang`, `text.<lang>` |
| Inspiration statements / family messages | `assets/config.js` → `text.<lang>.quotes`, `family` |
| Voice command words | `assets/config.js` → `text.<lang>.voice` |
| Music presets | `assets/config.js` → `music` |
| Themes / colours | `assets/config.js` → `themes` |
| Hospital analytics endpoint | `assets/config.js` → `analyticsUrl` (POST JSON per session) |
| App icon | `res/drawable/icon.xml` |
| Version | `version.json` |

## Release (versioning)
1. Bump `versionCode` (+1) and `versionName` in `version.json`.
2. Run `.\build.ps1` → `AshaDeep.apk` (signed with `key.jks`, keep it safe; same key is required for updates).
3. Commit `AshaDeep.apk` + `version.json` to `main` and tag: `git tag v1.1; git push --tags`.
4. Installed apps compare their version with `version.json` on GitHub main and show the **⬆ New** button.
