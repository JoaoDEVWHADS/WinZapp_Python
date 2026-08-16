"""Single source of truth for the portable Node.js download."""

NODE_VERSION = "22.22.2"
NODE_FILENAME = f"node-v{NODE_VERSION}-win-x64.zip"
NODE_URL = f"https://nodejs.org/dist/v{NODE_VERSION}/{NODE_FILENAME}"
NODE_SHASUMS_URL = (
    f"https://nodejs.org/dist/v{NODE_VERSION}/SHASUMS256.txt"
)
NODE_TOP_DIR = f"node-v{NODE_VERSION}-win-x64"
