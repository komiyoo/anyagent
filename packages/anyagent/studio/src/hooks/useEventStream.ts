import { useEffect, useState } from "react";
import { StudioDebugEvent, StudioSettings, streamPersistedEvents } from "../anyagentClient";

export function useEventStream(settings: StudioSettings, responseId: string) {
  const [liveEvents, setLiveEvents] = useState<StudioDebugEvent[]>([]);
  const [tailing, setTailing] = useState(false);
  const [streamStatus, setStreamStatus] = useState("idle");

  useEffect(() => {
    if (!tailing || !responseId) {
      return;
    }
    setLiveEvents([]);
    setStreamStatus("connecting");
    const stop = streamPersistedEvents(settings, responseId, {
      onEvent: (event) => {
        setStreamStatus("live");
        setLiveEvents((current) => [...current.slice(-199), event]);
      },
      onError: () => setStreamStatus("reconnecting"),
    });
    return () => {
      stop();
      setStreamStatus("idle");
    };
  }, [tailing, responseId, settings.baseUrl, settings.apiKey]);

  return { liveEvents, tailing, setTailing, streamStatus };
}
