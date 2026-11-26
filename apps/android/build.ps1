# Builds AshaDeep.apk without Gradle. Requires JDK17 + Android SDK (build-tools 34, platform 34).
$ErrorActionPreference='Stop'; Set-Location $PSScriptRoot
$T="$env:USERPROFILE\.androidtools"; $B="$T\sdk\build-tools\34.0.0"; $J=(Get-ChildItem -Dir "$T\jdk-17*")[0].FullName+"\bin"
$env:JAVA_HOME=Split-Path $J; $ErrorActionPreference='Continue'
$A="$T\sdk\platforms\android-34\android.jar"
Remove-Item build -Recurse -Force -EA 0; mkdir build\classes,build\dex | Out-Null
# Version comes from version.json (bump versionCode + versionName before each release)
$V=Get-Content version.json -Raw | ConvertFrom-Json
& $J\javac -encoding UTF-8 -source 8 -target 8 -cp $A -d build\classes src\com\parivar\ashadeep\Main.java
& $B\d8.bat --min-api 21 --lib $A --output build\dex (Get-ChildItem -Recurse build\classes\*.class).FullName
& $B\aapt2.exe compile --dir res -o build\res.zip
& $B\aapt2.exe link -o build\base.apk --manifest AndroidManifest.xml -I $A -A assets build\res.zip --version-code $V.versionCode --version-name $V.versionName
Push-Location build\dex; & $J\jar uf ..\base.apk classes.dex; Pop-Location
& $B\zipalign.exe -f 4 build\base.apk build\aligned.apk
if(!(Test-Path key.jks)){& $J\keytool -genkeypair -keystore key.jks -alias a -keyalg RSA -validity 10000 -storepass ashadeep -keypass ashadeep -dname "CN=AshaDeep"}
& $B\apksigner.bat sign --ks key.jks --ks-pass pass:ashadeep --out AshaDeep.apk build\aligned.apk
Write-Host "Built $PSScriptRoot\AshaDeep.apk"
