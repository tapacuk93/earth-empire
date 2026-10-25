"""Logging: one line per event to stderr (journald on the box), CloudWatch Logs and metrics there.

Every pipeline transition, run, failure and cost goes through `event()`, which writes a JSON line
that CloudWatch Logs Insights can query (fields: event, item, step, ...).
"""
from __future__ import annotations

import json
import logging
import sys
import threading

from . import config

log = logging.getLogger("ee")
_setup_done = False


def setup(stream: str = "backend") -> None:
    global _setup_done
    if _setup_done:
        return
    _setup_done = True
    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if config.CLOUDWATCH:
        try:
            import socket
            import watchtower
            h = watchtower.CloudWatchLogHandler(log_group_name=config.LOG_GROUP,
                                                log_stream_name=f"{stream}-{socket.gethostname()}",
                                                create_log_group=False, send_interval=10)
            h.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
            logging.getLogger().addHandler(h)
        except Exception as e:  # logging must never take the service down
            log.warning("cloudwatch logs unavailable: %s", e)


def event(name: str, level: int = logging.INFO, **fields) -> None:
    log.log(level, json.dumps({"event": name, **fields}, ensure_ascii=False, default=str))


_metric_lock = threading.Lock()


def metric(name: str, value: float = 1.0, unit: str = "Count", **dims) -> None:
    """A CloudWatch metric in namespace EarthEmpire. A no-op off the box."""
    if not config.CLOUDWATCH:
        return
    try:
        import boto3
        with _metric_lock:
            boto3.client("cloudwatch", region_name=config.REGION).put_metric_data(
                Namespace="EarthEmpire",
                MetricData=[{"MetricName": name, "Value": value, "Unit": unit,
                             "Dimensions": [{"Name": k, "Value": str(v)} for k, v in dims.items()]}])
    except Exception as e:
        log.warning("metric %s not sent: %s", name, e)
