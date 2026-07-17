import json
import multiprocessing
import socket

import pytest

from ai_tester.destination_policy import (
    DEFAULT_ALLOWED_NETWORKS,
    DestinationPolicy,
    HostConfirmationRequired,
)


def resolver_for(address):
    def resolve(host, port, *, type):
        family = socket.AF_INET6 if ":" in address else socket.AF_INET
        return [(family, type, 6, "", (address, port))]

    return resolve


def add_host_in_process(path, host, barrier):
    policy = DestinationPolicy(path)
    barrier.wait()
    policy.add_host(host)


def test_missing_configuration_is_created_with_local_networks(tmp_path):
    path = tmp_path / "allowed-destinations.json"

    policy = DestinationPolicy(path)

    assert path.exists()
    assert policy.allowed_networks == DEFAULT_ALLOWED_NETWORKS
    assert "api.openai.com" in policy.allowed_hosts
    assert "localhost" in policy.allowed_hosts
    assert json.loads(path.read_text())["allowed_networks"] == list(DEFAULT_ALLOWED_NETWORKS)


@pytest.mark.parametrize(
    "host,address",
    [
        ("127.0.0.1", "127.0.0.1"),
        ("10.20.30.40", "10.20.30.40"),
        ("172.20.1.2", "172.20.1.2"),
        ("192.168.1.20", "192.168.1.20"),
        ("::1", "::1"),
        ("fd00::42", "fd00::42"),
    ],
)
def test_default_local_ranges_are_allowed(tmp_path, host, address):
    policy = DestinationPolicy(tmp_path / "allowed.json")

    policy.require_allowed(host, [address])


def test_unknown_public_domain_requires_confirmation(tmp_path):
    policy = DestinationPolicy(tmp_path / "allowed.json")

    with pytest.raises(HostConfirmationRequired) as error:
        policy.require_allowed("llm.example.net", ["203.0.113.10"])

    assert error.value.host == "llm.example.net"
    assert error.value.addresses == ("203.0.113.10",)


def test_unknown_local_domain_also_requires_confirmation(tmp_path):
    policy = DestinationPolicy(tmp_path / "allowed.json")

    with pytest.raises(HostConfirmationRequired) as error:
        policy.require_allowed("ollama.internal", ["192.168.1.20"])

    assert error.value.host == "ollama.internal"


def test_confirmed_domain_is_saved_and_reloaded(tmp_path):
    path = tmp_path / "allowed.json"
    policy = DestinationPolicy(path)

    policy.add_host("LLM.Example.NET.")

    reloaded = DestinationPolicy(path)
    assert "llm.example.net" in reloaded.allowed_hosts
    reloaded.require_allowed("llm.example.net", ["203.0.113.10"])


def test_policy_reloads_confirmations_written_by_another_instance(tmp_path):
    path = tmp_path / "allowed.json"
    first = DestinationPolicy(path)
    second = DestinationPolicy(path)

    first.add_host("new.example.net")

    second.require_allowed("new.example.net", ["203.0.113.10"])


def test_concurrent_processes_do_not_lose_confirmed_hosts(tmp_path):
    path = tmp_path / "allowed.json"
    DestinationPolicy(path)
    context = multiprocessing.get_context("fork")
    barrier = context.Barrier(2)
    processes = [
        context.Process(
            target=add_host_in_process,
            args=(path, host, barrier),
        )
        for host in ("first.example.net", "second.example.net")
    ]

    for process in processes:
        process.start()
    for process in processes:
        process.join(5)

    assert [process.exitcode for process in processes] == [0, 0]
    reloaded = DestinationPolicy(path)
    assert {"first.example.net", "second.example.net"} <= set(reloaded.allowed_hosts)


def test_wildcard_domain_cannot_be_added(tmp_path):
    policy = DestinationPolicy(tmp_path / "allowed.json")

    with pytest.raises(ValueError, match="[Nn]om d’hôte"):
        policy.add_host("*.example.net")
