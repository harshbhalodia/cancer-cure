package com.parivar.ashadeep;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.speech.RecognitionListener;
import android.speech.RecognizerIntent;
import android.speech.SpeechRecognizer;
import android.view.WindowManager;
import android.webkit.JavascriptInterface;
import android.webkit.WebView;
import java.util.ArrayList;

public class Main extends Activity {
  WebView w;
  SpeechRecognizer sr;
  android.speech.tts.TextToSpeech tts;

  @Override protected void onCreate(Bundle b) {
    super.onCreate(b);
    tts = new android.speech.tts.TextToSpeech(this, s -> {});
    getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
    w = new WebView(this);
    w.getSettings().setJavaScriptEnabled(true);
    w.getSettings().setDomStorageEnabled(true);
    w.getSettings().setMediaPlaybackRequiresUserGesture(false);
    w.addJavascriptInterface(new Bridge(), "Android");
    // Serve assets from a virtual https origin so Google Analytics (which ignores file://) works
    w.setWebViewClient(new android.webkit.WebViewClient() {
      @Override public android.webkit.WebResourceResponse shouldInterceptRequest(WebView v, android.webkit.WebResourceRequest r) {
        Uri u = r.getUrl();
        if (!"ashadeep.app".equals(u.getHost())) return null;
        String p = u.getPath().substring(1), m = p.endsWith(".js") ? "text/javascript" : p.endsWith(".mp3") ? "audio/mpeg" : "text/html";
        try { return new android.webkit.WebResourceResponse(m, "utf-8", getAssets().open(p)); } catch (Exception e) { return null; }
      }
    });
    w.loadUrl("https://ashadeep.app/index.html");
    setContentView(w);
  }

  @Override protected void onPause() { super.onPause(); w.evaluateJavascript("pauseAll()", null); }
  @Override protected void onDestroy() { if (sr != null) sr.destroy(); tts.shutdown(); super.onDestroy(); }

  void js(String fn, String arg) {
    final String s = fn + "(" + org.json.JSONObject.quote(arg) + ")";
    runOnUiThread(() -> w.evaluateJavascript(s, null));
  }

  void startListening(String lang) {
    if (Build.VERSION.SDK_INT >= 23 && checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
      requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, 1);
      return;
    }
    if (sr == null) {
      sr = SpeechRecognizer.createSpeechRecognizer(this);
      sr.setRecognitionListener(new RecognitionListener() {
        public void onResults(Bundle r) {
          ArrayList<String> m = r.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
          js("onVoice", m == null ? "" : android.text.TextUtils.join(" ", m));
        }
        public void onError(int e) { js("say", "🎤 ?"); }
        public void onReadyForSpeech(Bundle p) {} public void onBeginningOfSpeech() {}
        public void onRmsChanged(float v) {} public void onBufferReceived(byte[] x) {}
        public void onEndOfSpeech() {} public void onPartialResults(Bundle p) {} public void onEvent(int t, Bundle p) {}
      });
    }
    Intent i = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
    i.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
    i.putExtra(RecognizerIntent.EXTRA_LANGUAGE, lang);
    i.putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 3);
    sr.startListening(i);
  }

  class Bridge {
    @JavascriptInterface public void listen(final String lang) { runOnUiThread(() -> startListening(lang)); }
    @JavascriptInterface public int versionCode() {
      try { return getPackageManager().getPackageInfo(getPackageName(), 0).versionCode; } catch (Exception e) { return 0; }
    }
    @JavascriptInterface public String versionName() {
      try { return getPackageManager().getPackageInfo(getPackageName(), 0).versionName; } catch (Exception e) { return ""; }
    }
    @JavascriptInterface public void speak(String t, String lang) {
      tts.setLanguage(java.util.Locale.forLanguageTag(lang));
      tts.setSpeechRate(0.9f);
      tts.speak(t, android.speech.tts.TextToSpeech.QUEUE_FLUSH, null, "a");
    }
    @JavascriptInterface public void openUrl(String u) { startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(u))); }
  }
}
