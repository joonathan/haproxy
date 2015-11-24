import logging
import os
import sys
import signal

import tutum

from haproxy import Haproxy
from parser import parse_uuid_from_resource_uri

__version__ = "0.2.1"
tutum.user_agent = "tutum-haproxy/%s" % __version__

DEBUG = os.getenv("DEBUG", False)
PIDFILE = "/tmp/tutum-haproxy.pid"

logger = logging.getLogger("haproxy")


def run_haproxy(msg=None):
    logger.info("==========BEGIN==========")
    if msg:
        logger.info(msg)
    haproxy = Haproxy()
    haproxy.update()


def tutum_event_handler(event):
    logger.debug(event)
    # When service scale up/down or container start/stop/terminate/redeploy, reload the service
    if event.get("state", "") not in ["In progress", "Pending", "Terminating", "Starting", "Scaling", "Stopping"] and \
                    event.get("type", "").lower() in ["container", "service"] and \
                    len(set(Haproxy.cls_linked_services).intersection(set(event.get("parents", [])))) > 0:
        msg = "Tutum event: %s %s is %s" % (
            event["type"], parse_uuid_from_resource_uri(event.get("resource_uri", "")), event["state"].lower())
        run_haproxy(msg)

    # Add/remove services linked to haproxy
    if event.get("state", "") == "Success" and Haproxy.cls_service_uri in event.get("parents", []):
        service = Haproxy.fetch_tutum_obj(Haproxy.cls_service_uri)
        service_endpoints = [srv.get("to_service") for srv in service.linked_to_service]
        if Haproxy.cls_linked_services != service_endpoints:
            services_unlinked = ", ".join([parse_uuid_from_resource_uri(uri) for uri in
                                           set(Haproxy.cls_linked_services) - set(service_endpoints)])
            services_linked = ", ".join([parse_uuid_from_resource_uri(uri) for uri in
                                         set(service_endpoints) - set(Haproxy.cls_linked_services)])
            msg = "Tutum event:"
            if services_unlinked:
                msg += " service %s is unlinked from HAProxy" % services_unlinked
            if services_linked:
                msg += " service %s is linked to HAProxy" % services_linked

            run_haproxy(msg)


def create_pid_file():
    pid = str(os.getpid())
    try:
        file(PIDFILE, 'w').write(pid)
    except Exception as e:
        logger.error("Cannot write to pidfile: %s" % e)
    return pid


def user_reload_haproxy(signum, frame):
    run_haproxy("User reload")


def main():
    logging.basicConfig(stream=sys.stdout)
    logging.getLogger("haproxy").setLevel(logging.DEBUG if DEBUG else logging.INFO)

    pid = create_pid_file()
    signal.signal(signal.SIGUSR1, user_reload_haproxy)
    signal.signal(signal.SIGTERM, sys.exit)

    if Haproxy.cls_container_uri and Haproxy.cls_service_uri:
        if Haproxy.cls_tutum_auth:
            logger.info(
                "Tutum-haproxy(PID: %s) has access to Tutum API - will reload list of backends in real-time" % pid)
        else:
            logger.warning(
                "Tutum-haproxy(PID: %s) doesn't have access to Tutum API and it's running in Tutum - you might want to"
                " give an API role to this service for automatic backend reconfiguration" % pid)
    else:
        logger.info("Tutum-haproxy(PID: %s) is not running in Tutum" % pid)

    if Haproxy.cls_container_uri and Haproxy.cls_service_uri and Haproxy.cls_tutum_auth:
        events = tutum.TutumEvents()
        events.on_open(lambda: run_haproxy("Websocket open"))
        events.on_close(lambda: logger.info("Websocket close"))
        events.on_message(tutum_event_handler)
        events.run_forever()
    else:
        run_haproxy("Initial start")


if __name__ == "__main__":
    main()
