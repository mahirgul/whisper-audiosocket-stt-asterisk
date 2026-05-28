// header.js — Updates the global header AI status dot
"use strict";

// Global API Fetch Interceptor for Passcode Protection
const originalFetch = window.fetch;
window.fetch = async function (url, options = {}) {
  options.headers = options.headers || {};
  
  const isRelative = (typeof url === 'string') && 
    (!url.startsWith("http://") && !url.startsWith("https://") || url.includes(window.location.host));
    
  if (isRelative) {
    const passcode = localStorage.getItem("wasa_passcode");
    if (passcode) {
      if (options.headers instanceof Headers) {
        options.headers.set("X-Passcode", passcode);
      } else {
        options.headers["X-Passcode"] = passcode;
      }
    }
  }

  let response = await originalFetch(url, options);

  if (response.status === 401 && isRelative) {
    const passcode = prompt("This WASA system is secured. Please enter the Web Passcode:");
    if (passcode !== null) {
      localStorage.setItem("wasa_passcode", passcode);
      // Retry the request
      if (options.headers instanceof Headers) {
        options.headers.set("X-Passcode", passcode);
      } else {
        options.headers["X-Passcode"] = passcode;
      }
      response = await originalFetch(url, options);
    }
  }

  return response;
};

document.addEventListener("DOMContentLoaded", () => {
  async function updateHeaderAIStatus() {
    try {
      const r = await fetch('/stats');
      const d = await r.json();
      const dot = document.getElementById('aiStatusDot');
      const text = document.getElementById('aiStatusText');
      if (dot && text) {
        if (d.status === "loading") {
          dot.style.background = "#eab308"; // Yellow
          text.innerText = "AI Loading...";
        } else if (d.status === "idle" || d.status === "processing") {
          dot.style.background = "#22c55e"; // Green
          text.innerText = "AI Online";
        } else {
          dot.style.background = "#94a3b8"; // Gray
          text.innerText = "AI Offline";
        }
      }
    } catch (e) {
      const dot = document.getElementById('aiStatusDot');
      const text = document.getElementById('aiStatusText');
      if (dot && text) {
        dot.style.background = "#94a3b8"; // Gray / offline
        text.innerText = "AI Offline";
      }
    }
  }

  updateHeaderAIStatus();
  setInterval(updateHeaderAIStatus, 3000); // Check every 3 seconds for header status
});
