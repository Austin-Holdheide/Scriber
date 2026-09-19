/**
 * Copy text to the clipboard, working on BOTH secure contexts (https/localhost)
 * and plain HTTP LAN origins.
 *
 * navigator.clipboard only exists in secure contexts; on http://192.168.1.202 it
 * is undefined. Fallback: hidden <textarea> + document.execCommand("copy"),
 * which browsers still honor inside a user-gesture handler.
 */
export async function copyText(text: string): Promise<boolean> {
  // 1) modern API when available (https / localhost)
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch { /* fall through */ }

  // 2) legacy fallback (works on plain HTTP inside a click handler)
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.top = "0";
    ta.style.left = "0";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    ta.setSelectionRange(0, text.length);
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}
