// header.js — Updates the global header AI status dot
"use strict";

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
