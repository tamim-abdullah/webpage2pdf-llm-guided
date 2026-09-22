const SERVER = "http://localhost:8000/clip";

// Runs inside the page. Promotes lazy-loaded images, then returns the HTML.
function grabPage() {
  document.querySelectorAll("img").forEach((img) => {
    const lazy =
      img.getAttribute("data-src") ||
      img.getAttribute("data-lazy-src") ||
      img.getAttribute("data-original");
    if (lazy && !img.src.startsWith("data:")) img.src = lazy;
    if (!img.getAttribute("src") && img.getAttribute("srcset")) {
      img.src = img.getAttribute("srcset").split(",")[0].trim().split(" ")[0];
    }
  });
  return document.documentElement.outerHTML;
}

const status = document.getElementById("status");
const button = document.getElementById("go");

button.addEventListener("click", async () => {
  button.disabled = true;
  status.textContent = "Reading page...";

  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const [{ result: html }] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: grabPage,
    });

    status.textContent = "Filtering and rendering...";

    const res = await fetch(SERVER, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        html,
        url: tab.url,
        title: tab.title,
        topic: document.getElementById("topic").value.trim(),
      }),
    });

    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Server error");

    status.textContent = `Saved: ${data.file}\nKept ${data.kept} of ${data.total} sections.`;
  } catch (err) {
    status.textContent = `Failed: ${err.message}`;
  } finally {
    button.disabled = false;
  }
});
