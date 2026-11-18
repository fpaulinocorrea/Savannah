# Shared helpers for Savannah's scripts.

export PATH="$HOME/.local/bin:$PATH"

# uv runs Savannah's Python code. It also downloads the right Python version if needed.
ensure_uv() {
  if command -v uv >/dev/null 2>&1; then return; fi
  echo "First time setup: installing uv (the Python helper)…"
  if command -v curl >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
  elif command -v wget >/dev/null 2>&1; then
    wget -qO- https://astral.sh/uv/install.sh | sh
  else
    echo "Savannah needs curl to finish setup. Run:  sudo apt install curl   then try again."
    exit 1
  fi
  export PATH="$HOME/.local/bin:$PATH"
}

savannah_is_running() {
  (echo >/dev/tcp/127.0.0.1/8800) >/dev/null 2>&1
}

open_browser() {
  xdg-open "http://localhost:8800" >/dev/null 2>&1 || true
}
