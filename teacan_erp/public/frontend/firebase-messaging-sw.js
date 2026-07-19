/* Firebase background push worker.
   PASTE THE SAME CONFIG as src/firebase.js below, then rebuild. */
importScripts("https://www.gstatic.com/firebasejs/10.12.0/firebase-app-compat.js");
importScripts("https://www.gstatic.com/firebasejs/10.12.0/firebase-messaging-compat.js");

firebase.initializeApp({
  apiKey: "",
  authDomain: "",
  projectId: "",
  messagingSenderId: "",
  appId: "",
});

const messaging = firebase.messaging();
messaging.onBackgroundMessage(function (p) {
  if (p && p.notification) return; // browser already shows notification payloads
  const d = (p && p.data) || {};
  self.registration.showNotification(d.title || "Shalini ERP", { body: d.body || "" });
});
