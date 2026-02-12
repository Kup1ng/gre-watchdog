# gre_watchdog/agent/main.py
import yaml
from gre_watchdog.common.log import setup_logger
from gre_watchdog.agent.api import build_agent_app

def load_cfg(path="config/agent.yaml"):
    with open(path, "r") as f:
        return yaml.safe_load(f)

CFG = load_cfg()
logger = setup_logger("gre-watchdog-agent", CFG["log_dir"])
app = build_agent_app(CFG, logger)
