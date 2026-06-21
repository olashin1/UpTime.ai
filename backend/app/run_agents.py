import subprocess
import sys
import time

agents = [
    "app.agents.investigation_agent",
    "app.agents.github_agent",
    "app.agents.patch_agent",
    "app.agents.validation_agent",
]

processes = []


def stop_agents():
    for process in processes:
        if process.poll() is None:
            process.terminate()

    time.sleep(2)

    for process in processes:
        if process.poll() is None:
            process.kill()


try:
    for agent in agents:
        print(f"Starting {agent}...", flush=True)
        p = subprocess.Popen([sys.executable, "-m", agent])
        processes.append(p)
        time.sleep(1)
        if p.poll() is not None:
            raise RuntimeError(f"{agent} exited during startup with code {p.returncode}")

    print("All agents started.", flush=True)

    for p in processes:
        return_code = p.wait()
        if return_code != 0:
            raise RuntimeError(f"Agent process exited with code {return_code}")

except KeyboardInterrupt:
    print("Stopping agents...", flush=True)
    stop_agents()
except Exception as exc:
    print(f"Failed to run agents: {exc}", file=sys.stderr, flush=True)
    stop_agents()
    raise SystemExit(1) from exc
