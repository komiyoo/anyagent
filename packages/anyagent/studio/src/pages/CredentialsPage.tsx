import { Button, Card, Input } from "@heroui/react";
import { KeyRound, RefreshCw } from "lucide-react";
import { FormEvent } from "react";
import { CredentialRef } from "../anyagentClient";

type CredentialsPageProps = {
  credentials: CredentialRef[];
  credentialId: string;
  credentialKind: string;
  credentialValue: string;
  credentialScope: "global" | "agent";
  credentialStatus: string;
  onLoadCredentials: () => void;
  onSubmitCredential: (event: FormEvent<HTMLFormElement>) => void;
  onRemoveCredential: (credentialId: string) => void;
  onCredentialIdChange: (value: string) => void;
  onCredentialKindChange: (value: string) => void;
  onCredentialValueChange: (value: string) => void;
  onCredentialScopeChange: (value: "global" | "agent") => void;
};

export function CredentialsPage({
  credentials,
  credentialId,
  credentialKind,
  credentialValue,
  credentialScope,
  credentialStatus,
  onLoadCredentials,
  onSubmitCredential,
  onRemoveCredential,
  onCredentialIdChange,
  onCredentialKindChange,
  onCredentialValueChange,
  onCredentialScopeChange,
}: CredentialsPageProps) {
  const isSaving = credentialStatus === "Saving";
  const isLoading = credentialStatus === "Loading" || credentialStatus === "Deleting";
  const idError = credentialId.trim() ? "" : "Credential id is required.";
  const kindError = credentialKind.trim() ? "" : "Kind is required.";
  const valueError = credentialValue.trim() ? "" : "Secret value is required.";

  return (
    <Card className="panel wide-panel compact-panel">
      <Card.Header className="panel-header">
        <div className="panel-title">
          <KeyRound size={18} />
          <span>Credential Vault</span>
        </div>
        <div className="editor-actions">
          <span>{credentialStatus}</span>
          <Button size="sm" variant="secondary" onPress={onLoadCredentials} isDisabled={isLoading}>
            {isLoading ? <span className="button-spinner" aria-hidden="true" /> : null}
            <RefreshCw size={15} />
            Refresh
          </Button>
        </div>
      </Card.Header>
      <Card.Content className="panel-content">
        <form className="credential-form" onSubmit={onSubmitCredential}>
          <label className="control-label">
            <span>Credential id</span>
            <Input aria-label="Credential id" value={credentialId} onChange={(event) => onCredentialIdChange(event.target.value)} />
            {idError ? <small className="field-error">{idError}</small> : null}
          </label>
          <label className="control-label">
            <span>Kind</span>
            <Input aria-label="Credential kind" value={credentialKind} onChange={(event) => onCredentialKindChange(event.target.value)} />
            {kindError ? <small className="field-error">{kindError}</small> : null}
          </label>
          <label className="control-label">
            <span>Secret value</span>
            <Input aria-label="Credential value" type="password" value={credentialValue} onChange={(event) => onCredentialValueChange(event.target.value)} />
            {valueError ? <small className="field-error">{valueError}</small> : null}
          </label>
          <label className="control-label">
            <span>Scope</span>
            <select className="native-select" aria-label="Credential scope" value={credentialScope} onChange={(event) => onCredentialScopeChange(event.target.value as "global" | "agent")}>
              <option value="agent">agent</option>
              <option value="global">global</option>
            </select>
          </label>
          <Button size="sm" variant="primary" type="submit" isDisabled={isSaving || Boolean(idError || kindError || valueError)}>
            {isSaving ? <span className="button-spinner" aria-hidden="true" /> : null}
            Save credential
          </Button>
        </form>
        <div className="credential-list">
          {credentials.length === 0 ? (
            <p className="empty">No credential references saved. Secret values are write-only and never shown again.</p>
          ) : (
            credentials.map((credential) => (
              <article className="credential-row" key={credential.credential_id}>
                <div>
                  <strong>{credential.credential_id}</strong>
                  <span>
                    {credential.kind} · {credential.scope.level}
                    {credential.scope.agent_id ? `/${credential.scope.agent_id}` : ""}
                  </span>
                </div>
                <Button size="sm" variant="secondary" onPress={() => onRemoveCredential(credential.credential_id)}>
                  Delete
                </Button>
              </article>
            ))
          )}
        </div>
      </Card.Content>
    </Card>
  );
}
