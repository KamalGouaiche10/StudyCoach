// Runs on the app origin through a Streamlit v2 component, not in an iframe.
export default function syncSessionCookie({ data, setStateValue }) {
  const readCookie = () => {
    const prefix = `${data.name}=`;
    const entry = document.cookie.split(";").map(value => value.trim())
      .find(value => value.startsWith(prefix));
    return entry ? decodeURIComponent(entry.slice(prefix.length)) : "";
  };
  let status;
  try {
    if (readCookie() !== data.value) {
      const secure = window.location.protocol === "https:" ? "; Secure" : "";
      document.cookie = `${data.name}=${encodeURIComponent(data.value)}; Max-Age=${data.maxAge}; Path=/; SameSite=Lax${secure}`;
    }
    status = readCookie() === data.value ? "saved" : "blocked";
  } catch {
    status = "blocked";
  }
  // At most one acknowledgement rerun, even when cookies are disabled.
  // Never redirect or put the credential in the URL.
  if (data.reported !== status) setStateValue("status", status);
}
