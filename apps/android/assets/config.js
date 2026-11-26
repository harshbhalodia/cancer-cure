// ===== AshaDeep configuration: edit this file to rebrand / re-language / retune =====
window.CFG = {
  brand: { hospital: "", app: "આશાદીપ", footer: "AshaDeep", tagline: "પરિવારનો પ્રેમ, જીવનની શક્તિ" },
  lang: "gu",                 // "gu" or "en"; also used for voice: gu-IN / en-IN
  updateUrl: "",              // Play Store build: updates come from Play. (GitHub self-update: raw version.json URL)
  analyticsUrl: "",           // optional hospital endpoint: POST JSON per event
  ga4: { measurementId: "G-RJ6NL35LNT", apiSecret: "" },   // GA4: gtag.js with ID only; apiSecret optional (Measurement Protocol)
  player: "👨",
  // Real bhajan / dayro recordings (that you have rights to). Local: put mp3 in assets/music and write "music/x.mp3".
  // Remote: full https URL to an mp3. Track changes every stage and on voice "ભજન". Empty = synthesized music only.
  bhajans: [],
  themes: ["linear-gradient(#1a2a6c,#b21f1f55,#fdbb2d)","linear-gradient(#0f3443,#34e89e)","linear-gradient(#41295a,#2F0743,#f8b500)","linear-gradient(#ff7e5f,#feb47b)"],
  // music: chords = soft pad; raga = tanpura drone + bansuri melody (+ manjira / temple bell). All original synthesized audio.
  music: [
    { name: "શ્રીનાથજી ઝાંખી", raga: { sa: 261.6, scale: [1,9/8,5/4,3/2,5/3,2,9/4], manjira: true, bell: true, tune: [0,1,2,2,3,2,1,0, 2,3,4,4,5,4,3,2, 4,5,6,5,4,3,2,1, 2,2,1,0,1,2,0,0] } },
    { name: "શ્રીનાથજી ઝાંખી – પ્રભાત", raga: { sa: 293.7, scale: [1,9/8,5/4,3/2,5/3,2], manjira: true, tune: [0,0,1,2,3,3,2,1, 3,4,5,4,3,2,1,0, 2,3,2,1,0,1,2,2, 4,3,2,1,1,0,0,0] } },
    { name: "શ્રીનાથજી ઝાંખી – સંધ્યા", raga: { sa: 233.1, scale: [1,9/8,5/4,3/2,5/3,2], manjira: true, bell: true, tune: [4,4,3,2,3,4,5,4, 3,2,1,2,3,2,1,0, 0,1,2,3,4,3,2,1, 2,1,0,1,2,1,0,0] } },
    { name: "શ્રીનાથજી ઝાંખી (ભૂપાલી)", raga: { sa: 261.6, scale: [1,9/8,5/4,3/2,5/3,2,9/4], manjira: true } },
    { name: "હવેલી કીર્તન (યમન)", raga: { sa: 293.7, scale: [1,9/8,5/4,45/32,3/2,5/3,15/8,2], manjira: true } },
    { name: "સાંજ આરતી (દુર્ગા)", raga: { sa: 220, scale: [1,9/8,4/3,3/2,5/3,2], manjira: true, bell: true } },
    { name: "મંગળા દર્શન (ભૈરવ)", raga: { sa: 246.9, scale: [1,16/15,5/4,4/3,3/2,8/5,15/8,2], bell: true } },
    { name: "રાજભોગ (દેશ)", raga: { sa: 277.2, scale: [1,9/8,5/4,4/3,3/2,5/3,16/9,2], manjira: true } },
    { name: "શયન (માલકૌંસ)", raga: { sa: 207.7, scale: [1,6/5,4/3,8/5,9/5,2] } },
    { name: "ગોકુળ (પહાડી)", raga: { sa: 261.6, scale: [1,9/8,5/4,3/2,5/3,2], manjira: true } },
    { name: "ડાયરો તાલ (કાફી)", raga: { sa: 233.1, scale: [1,9/8,6/5,4/3,3/2,5/3,9/5,2], manjira: true, bell: true } },
    { name: "શિવરંજની", raga: { sa: 220, scale: [1,9/8,6/5,3/2,5/3,2] } },
    { name: "હંસધ્વનિ", raga: { sa: 293.7, scale: [1,9/8,5/4,3/2,15/8,2], manjira: true } },
    { name: "ડાયરો – જય શ્રીનાથજી", raga: { sa: 246.9, scale: [1,9/8,5/4,4/3,3/2,5/3,2], manjira: true, bell: true, tune: [0,2,4,4,3,2,1,0, 4,5,6,5,4,3,2,2, 0,1,2,3,2,1,0,0, 3,4,5,4,3,2,1,0] } }
  ],
  // 20 worlds; each level moves to the next one (background, items, obstacle, music)
  stages: [
    { name: "🏡 ઘરનું આંગણું", bg: "linear-gradient(#1a2a6c,#b21f1f55,#fdbb2d)", good: ["🪔","❤️","🌸","⭐"], bad: "☁️", music: 0 },
    { name: "🦚 શ્રીનાથજી હવેલી", bg: "linear-gradient(#4a0072,#c2185b,#ffb300)", good: ["🦚","🪈","🧈","🌺","🪔"], bad: "🌧️", music: 3 },
    { name: "🌳 બગીચો", bg: "linear-gradient(#134e5e,#71b280)", good: ["🌼","🦋","🍎","🌻"], bad: "🐝", music: 1 },
    { name: "🛕 સાંજ આરતી", bg: "linear-gradient(#ff512f,#dd2476,#2b1055)", good: ["🔔","🪔","🥥","🌺","🙏"], bad: "💨", music: 5 },
    { name: "🌙 તારાઓનું આકાશ", bg: "linear-gradient(#000428,#004e92)", good: ["⭐","🌙","✨","🌟"], bad: "☄️", music: 2 },
    { name: "🌊 ગોમતી ઘાટ", bg: "linear-gradient(#2193b0,#6dd5ed)", good: ["🐚","🪷","🐟","🪔"], bad: "🌪️", music: 4 },
    { name: "🌅 મંગળા દર્શન", bg: "linear-gradient(#f83600,#f9d423)", good: ["🌅","🪔","🌸","🔔"], bad: "🌫️", music: 6 },
    { name: "🐄 ગોકુળ ગામ", bg: "linear-gradient(#56ab2f,#a8e063)", good: ["🐄","🥛","🧈","🪈"], bad: "🐍", music: 9 },
    { name: "🪁 ઉત્તરાયણ", bg: "linear-gradient(#36d1dc,#5b86e5)", good: ["🪁","🍬","🥜","☀️"], bad: "✂️", music: 1 },
    { name: "🪔 દિવાળી", bg: "linear-gradient(#200122,#6f0000)", good: ["🪔","🎆","🍬","💰","✨"], bad: "💥", music: 10 },
    { name: "💃 નવરાત્રી ગરબો", bg: "linear-gradient(#ee0979,#ff6a00)", good: ["🥁","🌺","🪘","💃","🔱"], bad: "🌀", music: 10 },
    { name: "🌾 ખેતર", bg: "linear-gradient(#e6dada,#f7b733,#6a9113)", good: ["🌾","🌽","🥭","🚜"], bad: "🐀", music: 7 },
    { name: "🏏 ક્રિકેટ મેદાન", bg: "linear-gradient(#11998e,#38ef7d)", good: ["🏏","🏆","🎯","⭐"], bad: "🦆", music: 12 },
    { name: "🍛 રસોડું", bg: "linear-gradient(#f12711,#f5af19)", good: ["🍛","🫓","🥭","🍵"], bad: "🌶️", music: 13 },
    { name: "⛰️ ગિરનાર", bg: "linear-gradient(#3e5151,#decba4)", good: ["🛕","🚩","🙏","🌄"], bad: "🪨", music: 11 },
    { name: "🌧️ ચોમાસું", bg: "linear-gradient(#4b6cb7,#182848)", good: ["☔","🌈","🐸","🌿"], bad: "⚡", music: 8 },
    { name: "✈️ દીકરાનો દેશ", bg: "linear-gradient(#0052d4,#65c7f7,#9cecfb)", good: ["✈️","📱","🎁","❤️"], bad: "🌩️", music: 13 },
    { name: "🎡 મેળો", bg: "linear-gradient(#fc466b,#3f5efb)", good: ["🎡","🍭","🎈","🧸"], bad: "🎃", music: 12 },
    { name: "🌸 વસંત", bg: "linear-gradient(#ffafbd,#ffc3a0)", good: ["🌸","🌷","🐦","🍃"], bad: "🥀", music: 4 },
    { name: "👑 રાજભોગ દર્શન", bg: "linear-gradient(#b8860b,#ffd700,#8b0000)", good: ["👑","🦚","🍯","🪷","🪔"], bad: "🌑", music: 7 }
  ],
  text: {
    gu: {
      start: "▶ નવેસરથી રમો", resume: "⏯ સ્તર {n} થી આગળ રમો", next: "આગળ ▶", level: "સ્તર",
      howto: "{p} તમે છો પરિવારના મોભી.<br>આંગળીથી ખસેડો અને વસ્તુઓ પકડો.<br>નીચેની ખરાબ વસ્તુથી બચો.<br>🎤 બોલો: શરૂ, થોભો, ધીમે, અવાજ વધારો, સંગીત બદલો, ભજન, રંગ બદલો",
      welcome: "ફરી સ્વાગત છે! 🙏", miss: "અરે! ચાલો ફરી 😄", heard: "🎤 સાંભળ્યું: ",
      listening: "🎤 બોલો, હું સાંભળું છું...", update: "⬆ નવું", stats: "આજે {m} મિનિટ • કુલ {s} વખત રમ્યા",
      breath: ["🌬️ ઊંડો શ્વાસ લો...", "😌 રોકો...", "🍃 ધીમેથી છોડો..."],
      family: [
        ["👴👵","બાપુજી અને બા","બેટા, તું અમારો સિંહ છે. તારા પર અમને ગર્વ છે! 🙏"],
        ["👨‍✈️✈️","વિદેશથી દીકરો","પપ્પા, હું દૂર છું પણ દિલથી હંમેશા તમારી પાસે છું. જલ્દી મળીશું! ❤️"],
        ["👦","પૌત્ર","દાદા, તમે મારા હીરો છો! આજે સાંજે ક્રિકેટ રમીશું? 🏏"],
        ["👨‍👩‍👧‍👦","પિતરાઈ ભાઈ-બહેન","તમારા વગર પરિવારનો મેળાવડો અધૂરો છે! 🌸"],
        ["👩","જીવનસાથી","તમારું હાસ્ય આખા ઘરને અજવાળે છે. 💛"],
        ["📱","દીકરાનો વીડિયો કૉલ","પપ્પા, તમારી વાતો સાંભળીને મારો દિવસ બની જાય છે! 😊"],
        ["👧","પૌત્રી","દાદા, મેં તમારા માટે ચિત્ર બનાવ્યું છે. જોવા આવશો ને? 🎨"],
        ["🏡","આખું ઘર","આ વખતે તહેવાર તમે જ શરૂ કરાવશો! 🎉"],
        ["🧑‍🤝‍🧑","જૂના મિત્રો","ચાલો, ચાની કીટલી પર જૂની વાતો કરીએ! ☕"],
        ["🐄","ગામ","ગામનું ચોરો તમારી વાર્તાઓની રાહ જુએ છે. 🌳"],
        ["🌅","નવી સવાર","દરેક સૂર્યોદય નવી ખુશી લાવે છે. ⭐"]
      ],
      quotes: [
        "વાહ! શું પકડ છે! 👏","પરિવાર તમારી તાકાત છે ❤️","જય શ્રીનાથજી 🙏","જય શ્રી કૃષ્ણ 🙏","તમે તો ચેમ્પિયન છો 🏆",
        "દીકરો તમારી વાટ જુએ છે 📱","આજનો દિવસ તમારો છે 🌟","તમારું સ્મિત ઘરનો દીવો છે 🪔","એક પગલું, એક જીત 👣",
        "પૌત્ર તમારી સાથે ક્રિકેટ રમવા રાહ જુએ છે 🏏","તમે ધાર્યું તે કરી શકો છો ✨","બધાના આશીર્વાદ તમારી સાથે છે 🤲",
        "અંધારા પછી અજવાળું આવે જ છે 🌄","તમારી હિંમત બધાને પ્રેરણા આપે છે 🔥","ખૂબ સરસ! આગળ વધો 🚀","જય માતાજી 🙏",
        "દીકરો કહે છે: આઈ લવ યુ પપ્પા ❤️","મોભી હોય તો આવા! 💪","તમારી વાર્તાઓ સાંભળવા બધા આતુર છે 📖",
        "શ્રીનાથજીની કૃપા અપાર છે 🦚","મન પ્રસન્ન, દિવસ પ્રસન્ન 😊","શાબાશ! બધા તાળી પાડે છે 👏","તમારા અનુભવનો ખજાનો અમૂલ્ય છે 💎",
        "આજે તો કમાલ કરી! 🎉","ઘરમાં તમારો અવાજ સંગીત જેવો છે 🎶","દુનિયા તમારા હાથમાં છે 🌍","તમે બોલો, અમે સાંભળીએ 👂"
      ],
      voice: { start:["શરૂ","ચાલુ"], stop:["બંધ"], pause:["થોભ","રોક","ઉભા"], slow:["ધીમ"], fast:["ઝડપ","જલ્દી"],
               volup:["અવાજ વધાર","મોટ","વધાર"], voldown:["અવાજ ઘટાડ","ધીર","ઓછ"], bhajan:["ભજન","શ્રીનાથ","ભગવાન","કીર્તન","આરતી","ડાયરો","ઝાંખી"],
               music:["સંગીત","ગીત","મ્યુઝિક"], theme:["રંગ","થીમ"] },
      replies: { start:"ચાલો, રમીએ! તમે કરી શકો છો.", pause:"ઠીક છે, થોડો વિરામ. હું અહીં જ છું.", slow:"બરાબર, ધીમે ધીમે રમીએ.",
                 fast:"વાહ! ઝડપ વધારું છું.", volup:"અવાજ વધાર્યો.", voldown:"અવાજ ઓછો કર્યો.", music:"તમારી પસંદનું નવું સંગીત.",
                 bhajan:"જય શ્રીનાથજી! ભજન ચાલુ કરું છું.", theme:"નવો રંગ, નવી ઉર્જા!", none:"ફરી બોલશો? હું સાંભળું છું.",
                 stage:"હવે આપણે જઈએ છીએ" }
    },
    en: {
      start: "▶ New game", resume: "⏯ Continue from level {n}", next: "Next ▶", level: "Level",
      howto: "{p} You are the head of the family.<br>Slide your finger to catch items.<br>Avoid the bad one.<br>🎤 Say: start, pause, slow, volume up, change music, bhajan, change theme",
      welcome: "Welcome back! 🙏", miss: "Oops! Let's go again 😄", heard: "🎤 Heard: ",
      listening: "🎤 Speak, I am listening...", update: "⬆ New", stats: "Today {m} min • played {s} times",
      breath: ["🌬️ Breathe in deeply...", "😌 Hold...", "🍃 Breathe out slowly..."],
      family: [
        ["👴👵","Father & Mother","Son, you are our lion. We are proud of you! 🙏"],
        ["👨‍✈️✈️","Son abroad","Papa, I am far away but always with you in my heart! ❤️"],
        ["👦","Grandson","Grandpa, you are my hero! Cricket this evening? 🏏"],
        ["👨‍👩‍👧‍👦","Cousins","Family gatherings are incomplete without you! 🌸"],
        ["🌅","New morning","Every sunrise brings new joy. ⭐"]
      ],
      quotes: ["What a catch! 👏","Family is your strength ❤️","Jai Shreenathji 🙏","You are a champion 🏆","Today is your day 🌟",
               "Your smile lights the home 🪔","The world is in your hands 🌍","You speak, we listen 👂"],
      voice: { start:["start","play"], stop:["stop"], pause:["pause","wait"], slow:["slow"], fast:["fast"],
               volup:["volume up","louder"], voldown:["volume down","quieter"], bhajan:["bhajan","shreenath","shrinath","god","aarti","dayro"],
               music:["music","song"], theme:["theme","colour","color"] },
      replies: { start:"Let's play! You can do it.", pause:"Okay, a short break. I am right here.", slow:"Sure, let's go slowly.",
                 fast:"Wow! Going faster.", volup:"Volume up.", voldown:"Volume down.", music:"New music for you.",
                 bhajan:"Jai Shreenathji! Playing bhajan.", theme:"New colour, new energy!", none:"Say again? I am listening.",
                 stage:"Now we go to" }
    }
  }
};
