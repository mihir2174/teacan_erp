/* Firebase background push worker.
   PASTE THE SAME CONFIG as src/firebase.js below, then rebuild. */
importScripts("https://www.gstatic.com/firebasejs/10.12.0/firebase-app-compat.js");
importScripts("https://www.gstatic.com/firebasejs/10.12.0/firebase-messaging-compat.js");

firebase.initializeApp({
  apiKey: "AIzaSyB0aUIMBanSuYR5YqkqOjN2B5MVxYd3nU0",
  authDomain: "shalini-erp-fe020.firebaseapp.com",
  projectId: "shalini-erp-fe020",
  storageBucket: "shalini-erp-fe020.firebasestorage.app",
  messagingSenderId: "443383003422",
  appId: "1:443383003422:web:6b0b414ecd71aa6136710f"
});

const messaging = firebase.messaging();
messaging.onBackgroundMessage(function (p) {
  if (p && p.notification) return; // browser already shows notification payloads
  const d = (p && p.data) || {};
  self.registration.showNotification(d.title || "Shalini ERP", { body: d.body || "" });
});
