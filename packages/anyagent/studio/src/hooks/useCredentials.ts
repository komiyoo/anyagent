import { FormEvent, useEffect, useState } from "react";
import {
  CredentialRef,
  StudioSettings,
  deleteCredential,
  listCredentials,
  setCredential,
} from "../anyagentClient";

export function useCredentials(settings: StudioSettings) {
  const [credentials, setCredentials] = useState<CredentialRef[]>([]);
  const [credentialId, setCredentialId] = useState("cred_amap");
  const [credentialKind, setCredentialKind] = useState("bearer_token");
  const [credentialValue, setCredentialValue] = useState("");
  const [credentialScope, setCredentialScope] = useState<"global" | "agent">("agent");
  const [credentialStatus, setCredentialStatus] = useState("Not loaded");

  async function loadCredentials() {
    setCredentialStatus("Loading");
    try {
      const payload = await listCredentials(settings);
      setCredentials(payload.credentials);
      setCredentialStatus(`${payload.credentials.length} saved`);
    } catch (error) {
      setCredentials([]);
      setCredentialStatus(error instanceof Error ? error.message : "Load failed");
    }
  }

  async function submitCredential(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setCredentialStatus("Saving");
    try {
      const ref = await setCredential(
        settings,
        credentialId.trim(),
        credentialKind.trim(),
        credentialValue,
        credentialScope,
        settings.agentId,
      );
      setCredentialStatus(`Saved ${ref.credential_id}`);
      setCredentialValue("");
      await loadCredentials();
    } catch (error) {
      setCredentialStatus(error instanceof Error ? error.message : "Save failed");
    }
  }

  async function removeCredential(id: string) {
    setCredentialStatus("Deleting");
    try {
      await deleteCredential(settings, id);
      await loadCredentials();
    } catch (error) {
      setCredentialStatus(error instanceof Error ? error.message : "Delete failed");
    }
  }

  useEffect(() => {
    void loadCredentials();
  }, [settings.baseUrl, settings.adminKey, settings.agentId]);

  return {
    credentials,
    credentialId,
    credentialKind,
    credentialValue,
    credentialScope,
    credentialStatus,
    loadCredentials,
    removeCredential,
    setCredentialId,
    setCredentialKind,
    setCredentialScope,
    setCredentialValue,
    submitCredential,
  };
}
