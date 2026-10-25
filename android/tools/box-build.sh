#!/bin/bash
# Build and test the Android app on the earth-empire box (arm64 Ubuntu, reached over SSM), so no
# Android SDK or Gradle cache is needed on this machine.
#
#   android/tools/box-build.sh [gradle tasks...]          default: testDebugUnitTest assembleDebug
#   EE_SCREENSHOTS=1 android/tools/box-build.sh           also renders the screenshot tests
#
# The source goes up as a tarball through the private bucket earth-empire-backups
# (android-build/), Gradle runs as the user `abuild` in /srv/ee-android, and the reports, APK and
# screenshots come back to $OUT (default /tmp/ee-android-out).
#
# The box holds: JDK 17 (arm64), the SDK in /srv/ee-android/sdk, qemu-user + libc6:amd64 so
# Google's x86_64-only aapt2 runs, and an x86_64 Temurin JDK 17 in /srv/ee-android/jdk17-x64 for
# Robolectric's native graphics (it ships no linux-arm64 library).
set -euo pipefail
cd "$(dirname "$0")/../.."
TASKS="${*:-testDebugUnitTest assembleDebug}"
OUT="${OUT:-/tmp/ee-android-out}"
BUCKET=s3://earth-empire-backups/android-build
STAMP=$(date +%s)
tar czf /tmp/ee-android-src.tgz --exclude=build --exclude=.gradle --exclude=.kotlin -C . android
aws s3 cp --only-show-errors /tmp/ee-android-src.tgz "$BUCKET/src-$STAMP.tgz"
SHOTS=""
[ -n "${EE_SCREENSHOTS:-}" ] && SHOTS=1
backend/deploy/box-run.sh "
set -uo pipefail
sudo -u abuild -H bash -lc '
set -uo pipefail
export ANDROID_HOME=/srv/ee-android/sdk GRADLE_USER_HOME=/srv/ee-android/gradle-home JAVA_HOME=/usr/lib/jvm/java-17-openjdk-arm64
W=/srv/ee-android/work; mkdir -p \$W; cd \$W
aws s3 cp --only-show-errors $BUCKET/src-$STAMP.tgz src.tgz && rm -rf android/app/src && tar xzf src.tgz && cd android
echo sdk.dir=\$ANDROID_HOME > local.properties
rm -rf app/build/test-results app/build/reports app/build/screenshots
./gradlew --console=plain $TASKS > /srv/ee-android/last-build.log 2>&1; RC=\$?
if [ -n \"$SHOTS\" ] && [ \$RC = 0 ]; then
  ./gradlew --console=plain testDebugUnitTest --tests \"*ScreenshotTest*\" -Pee.screenshots=1 -Pee.testJava=/srv/ee-android/jdk17-x64/bin/java >> /srv/ee-android/last-build.log 2>&1; RC=\$?
fi
tar czf /tmp/ee-out.tgz -C /srv/ee-android last-build.log -C work/android gradle/wrapper \$(cd app && ls -d build/test-results build/reports/tests build/outputs/apk build/screenshots 2>/dev/null | sed s,^,app/,) 2>/dev/null
aws s3 cp --only-show-errors /tmp/ee-out.tgz $BUCKET/out-$STAMP.tgz
grep -E \"^(BUILD|FAILURE|e: |w: .*deprecat)|tests completed|> Task :app:test|FAILED|PASSED|SKIPPED\" /srv/ee-android/last-build.log | grep -v -E \"^w: \" | tail -120
exit \$RC
'
" || RC=$?
rm -rf "$OUT" && mkdir -p "$OUT"
aws s3 cp --only-show-errors "$BUCKET/out-$STAMP.tgz" /tmp/ee-android-out.tgz && tar xzf /tmp/ee-android-out.tgz -C "$OUT"
aws s3 rm --only-show-errors "$BUCKET/src-$STAMP.tgz"; aws s3 rm --only-show-errors "$BUCKET/out-$STAMP.tgz"
echo "results in $OUT"
exit ${RC:-0}
