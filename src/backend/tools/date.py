from datetime import datetime, timezone
from langchain_core.tools import tool


@tool
def get_current_date_tool() -> str:
    """Get the current date and time.

    Returns:
        Current date and time in multiple formats.
    """
    now = datetime.now()
    utc_now = datetime.now(timezone.utc)

    return f"""Current Date/Time:
- Local: {now.strftime("%Y-%m-%d %H:%M:%S")}
- UTC: {utc_now.strftime("%Y-%m-%d %H:%M:%S")}
- ISO: {now.isoformat()}
- Day: {now.strftime("%A")}
- Date: {now.strftime("%B %d, %Y")}
- Time: {now.strftime("%I:%M %p")}
- Unix timestamp: {int(now.timestamp())}"""
