# Builds AshaDeep.apk (sideload) and AshaDeep.aab (Google Play) without Gradle.
# Requires JDK17 + Android SDK (build-tools 36, platform 36) + bundletool.jar in %USERPROFILE%\.androidtools
Set-Location $PSScriptRoot
$T="$env:USERPROFILE\.androidtools"; $B="$T\sdk\build-tools\36.0.0"; $J=(Get-ChildItem -Dir "$T\jdk-17*")[0].FullName+"\bin"
$env:JAVA_HOME=Split-Path $J
$A="$T\sdk\platforms\android-36\android.jar"
Remove-Item build -Recurse -Force -EA 0; mkdir build\classes,build\dex | Out-Null
# Version comes from version.json (bump versionCode + versionName before each release)
$V=Get-Content version.json -Raw | ConvertFrom-Json
$L=@('-I',$A,'-A','assets','build\res.zip','--manifest','AndroidManifest.xml','--version-code',$V.versionCode,'--version-name',$V.versionName)
& $J\javac -encoding UTF-8 -source 8 -target 8 -cp $A -d build\classes src\com\parivar\ashadeep\Main.java
& $B\d8.bat --min-api 24 --lib $A --output build\dex (Get-ChildItem -Recurse build\classes\*.class).FullName
& $B\aapt2.exe compile --dir res -o build\res.zip
# --- APK ---
& $B\aapt2.exe link -o build\base.apk @L
Push-Location build\dex; & $J\jar uf ..\base.apk classes.dex; Pop-Location
& $B\zipalign.exe -f 4 build\base.apk build\aligned.apk
if(!(Test-Path key.jks)){& $J\keytool -genkeypair -keystore key.jks -alias a -keyalg RSA -validity 10000 -storepass ashadeep -keypass ashadeep -dname "CN=AshaDeep"}
& $B\apksigner.bat sign --ks key.jks --ks-pass pass:ashadeep --out AshaDeep.apk build\aligned.apk
# --- AAB (Play) ---
& $B\aapt2.exe link --proto-format -o build\proto.apk @L
mkdir build\mod\manifest,build\mod\dex | Out-Null
Push-Location build\mod; & $J\jar xf ..\proto.apk; Pop-Location
Move-Item build\mod\AndroidManifest.xml build\mod\manifest\; Copy-Item build\dex\classes.dex build\mod\dex\
& $J\jar cMf build\base.zip -C build\mod .
Remove-Item AshaDeep.aab -EA 0
& $J\java -jar "$T\bundletool.jar" build-bundle --modules=build\base.zip --output=AshaDeep.aab
& $J\jarsigner -keystore key.jks -storepass ashadeep AshaDeep.aab a | Out-Null
Write-Host "Built AshaDeep.apk and AshaDeep.aab v$($V.versionName) ($($V.versionCode))"
