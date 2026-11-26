// ===== AshaDeep configuration: edit this file to rebrand / re-language / retune =====
window.CFG = {
  brand: { hospital: "આપની હોસ્પિટલ", app: "આશાદીપ", tagline: "પરિવારનો પ્રેમ, જીવનની શક્તિ" },
  lang: "gu",                 // "gu" or "en" (add more blocks below); also used for voice: gu-IN / en-IN
  updateUrl: "https://raw.githubusercontent.com/harshbhalodia/cancer-cure/main/apps/android/version.json",
  analyticsUrl: "",           // optional hospital endpoint: POST JSON session records
  player: "👨",
  good: ["🪔", "❤️", "🌸", "⭐", "🙏"], bad: "☁️",
  themes: [
    "linear-gradient(#1a2a6c,#b21f1f55,#fdbb2d)",
    "linear-gradient(#0f3443,#34e89e)",
    "linear-gradient(#41295a,#2F0743,#f8b500)",
    "linear-gradient(#ff7e5f,#feb47b)"
  ],
  // music presets: chord progressions (Hz). Soft pad + bells, original synthesized audio
  music: [
    { name: "શાંતિ", chords: [[216,272,324],[192,242,288],[162,204,243],[182,229,272]] },
    { name: "પ્રભાત", chords: [[264,330,396],[297,371,445],[220,277,330],[247,311,370]] },
    { name: "ધ્યાન", chords: [[144,216,288],[128,192,256],[162,243,324],[144,216,288]] }
  ],
  text: {
    gu: {
      start: "▶ નવેસરથી રમો", resume: "⏯ સ્તર {n} થી આગળ રમો", next: "આગળ ▶", level: "સ્તર",
      howto: "{p} તમે છો પરિવારના મોભી.<br>આંગળીથી ખસેડો અને<br>🪔 ❤️ 🌸 ⭐ પકડો.<br>☁️ કાળા વાદળથી બચો.<br>🎤 બોલો: શરૂ, થોભો, ધીમે, અવાજ વધારો, સંગીત બદલો, રંગ બદલો",
      welcome: "ફરી સ્વાગત છે! 🙏", miss: "ચિંતા નહીં, ફરી પ્રયત્ન કરો 🙂", heard: "🎤 સાંભળ્યું: ",
      listening: "🎤 બોલો...", update: "⬆ નવું", stats: "આજે {m} મિનિટ • કુલ {s} વખત રમ્યા",
      breath: ["🌬️ ઊંડો શ્વાસ લો...", "😌 રોકો...", "🍃 ધીમેથી છોડો..."],
      family: [
        ["👴👵","બાપુજી અને બા","બેટા, તું અમારો સિંહ છે. હિંમત રાખ, ભગવાન તારી સાથે છે. 🙏"],
        ["👨‍✈️✈️","વિદેશથી દીકરો","પપ્પા, હું દૂર છું પણ દિલથી હંમેશા તમારી પાસે છું. જલ્દી મળીશું! ❤️"],
        ["👦","પૌત્ર","દાદા, તમે મારા હીરો છો! સાથે રમવા જલ્દી સાજા થઈ જાઓ. 🏏"],
        ["👨‍👩‍👧‍👦","પિતરાઈ ભાઈ-બહેન","આખો પરિવાર તમારા માટે પ્રાર્થના કરે છે. તમે એકલા નથી! 🌸"],
        ["👩","જીવનસાથી","દરરોજ થોડા વધુ મજબૂત. આપણે સાથે જીતીશું. 💪"],
        ["📱","દીકરાનો વીડિયો કૉલ","પપ્પા, તમારું હસતું મોઢું જોઈને મારો દિવસ બની જાય છે! 😊"],
        ["👧","પૌત્રી","દાદા, મેં તમારા માટે ચિત્ર બનાવ્યું છે. જલ્દી ઘરે આવો! 🎨"],
        ["🏡","આખું ઘર","ઘરનું આંગણું તમારી રાહ જુએ છે. તહેવાર સાથે ઉજવીશું! 🎉"],
        ["🌅","નવી સવાર","દરેક સૂર્યોદય નવી આશા લાવે છે. તમે જીતી રહ્યા છો! ⭐"]
      ],
      quotes: [
        "હિંમત એ જ દવા છે 💪","દીકરો વીડિયો કૉલ પર રાહ જુએ છે 📱","શાબાશ! 👏","પરિવાર તમારી તાકાત છે ❤️",
        "જય શ્રી કૃષ્ણ 🙏","દરેક દિવસ એક જીત છે 🌟","હસતા રહો, સાજા થાઓ 😊","તમે યોદ્ધા છો ⚔️",
        "ધીરજ રાખો, સારા દિવસો આવશે 🌈","તમારું સ્મિત ઘરનો દીવો છે 🪔","ભગવાન પર ભરોસો રાખો 🙏",
        "એક શ્વાસ, એક પગલું, એક જીત 👣","પૌત્ર તમારી સાથે ક્રિકેટ રમવા રાહ જુએ છે 🏏","તમે ધાર્યું તે કરી શકો છો ✨",
        "આજનો દિવસ ગઈકાલ કરતાં સારો 🌻","શરીર સાજું થાય છે, મન મજબૂત છે 🧘","બધાના આશીર્વાદ તમારી સાથે છે 🤲",
        "અંધારા પછી અજવાળું આવે જ છે 🌄","તમારી હિંમત બધાને પ્રેરણા આપે છે 🔥","ખૂબ સરસ! આગળ વધો 🚀",
        "જય માતાજી 🙏","દવા સાથે દુઆ પણ કામ કરે છે 💊❤️","દીકરો કહે છે: આઈ લવ યુ પપ્પા ❤️"
      ],
      // voice keywords (any match). Lowercase English always also accepted.
      voice: { start:["શરૂ","ચાલુ"], stop:["બંધ"], pause:["થોભ","રોક","ઉભા"], slow:["ધીમ"], fast:["ઝડપ","જલ્દી"],
               volup:["અવાજ વધાર","મોટ","વધાર"], voldown:["અવાજ ઘટાડ","ધીર","ઓછ"], music:["સંગીત","ગીત","મ્યુઝિક"], theme:["રંગ","થીમ"] }
    },
    en: {
      start: "▶ New game", resume: "⏯ Continue from level {n}", next: "Next ▶", level: "Level",
      howto: "{p} You are the head of the family.<br>Slide your finger to catch<br>🪔 ❤️ 🌸 ⭐. Avoid ☁️ clouds.<br>🎤 Say: start, pause, slow, volume up, change music, change theme",
      welcome: "Welcome back! 🙏", miss: "No worry, try again 🙂", heard: "🎤 Heard: ",
      listening: "🎤 Speak...", update: "⬆ New", stats: "Today {m} min • played {s} times",
      breath: ["🌬️ Breathe in deeply...", "😌 Hold...", "🍃 Breathe out slowly..."],
      family: [
        ["👴👵","Father & Mother","Son, you are our lion. Stay brave, God is with you. 🙏"],
        ["👨‍✈️✈️","Son abroad","Papa, I am far away but always with you in my heart! ❤️"],
        ["👦","Grandson","Grandpa, you are my hero! Get well soon to play with me. 🏏"],
        ["👨‍👩‍👧‍👦","Cousins","The whole family prays for you. You are not alone! 🌸"],
        ["🌅","New morning","Every sunrise brings new hope. You are winning! ⭐"]
      ],
      quotes: ["Courage is medicine 💪","Well done! 👏","Family is your strength ❤️","Every day is a victory 🌟",
               "Keep smiling, keep healing 😊","You are a warrior ⚔️","After darkness comes light 🌄","One breath, one step, one win 👣"],
      voice: { start:["start","play"], stop:["stop"], pause:["pause","wait"], slow:["slow"], fast:["fast"],
               volup:["volume up","louder"], voldown:["volume down","quieter"], music:["music","song"], theme:["theme","colour","color"] }
    }
  }
};
