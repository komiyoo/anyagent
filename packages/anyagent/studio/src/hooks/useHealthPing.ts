import { useEffect, useRef, useState } from "react";
import { getHealth, StudioSettings } from "../anyagentClient";

export type HealthState = "checking" | "healthy" | "degraded" | "down";

export type HealthPing = {
  state: HealthState;
  latencyMs: number | null;
  lastCheckedAt: number | null;
};

const POLL_INTERVAL_MS = 15_000;
const REQUEST_TIMEOUT_MS = 8_000;
const DEGRADED_LATENCY_MS = 2_000;

const TIMEOUT = Symbol("health-ping-timeout");

export function useHealthPing(settings: StudioSettings): HealthPing {
  const [ping, setPing] = useState<HealthPing>({ state: "checking", latencyMs: null, lastCheckedAt: null });
  const inFlightRef = useRef(false);

  useEffect(() => {
    let mounted = true;

    const probe = async () => {
      if (inFlightRef.current) {
        return;
      }
      inFlightRef.current = true;
      const startedAt = performance.now();
      try {
        const timeout = new Promise<typeof TIMEOUT>((resolve) =>
          window.setTimeout(() => resolve(TIMEOUT), REQUEST_TIMEOUT_MS),
        );
        const outcome = await Promise.race([getHealth(settings).then(() => "ok" as const), timeout]);
        if (!mounted) {
          return;
        }
        if (outcome === TIMEOUT) {
          setPing({ state: "down", latencyMs: null, lastCheckedAt: Date.now() });
          return;
        }
        const latencyMs = Math.round(performance.now() - startedAt);
        setPing({
          state: latencyMs > DEGRADED_LATENCY_MS ? "degraded" : "healthy",
          latencyMs,
          lastCheckedAt: Date.now(),
        });
      } catch {
        if (mounted) {
          setPing({ state: "down", latencyMs: null, lastCheckedAt: Date.now() });
        }
      } finally {
        inFlightRef.current = false;
      }
    };

    setPing((current) => ({ ...current, state: "checking" }));
    void probe();
    const intervalId = window.setInterval(() => void probe(), POLL_INTERVAL_MS);

    return () => {
      mounted = false;
      window.clearInterval(intervalId);
    };
  }, [settings.baseUrl, settings.apiKey]);

  return ping;
}
