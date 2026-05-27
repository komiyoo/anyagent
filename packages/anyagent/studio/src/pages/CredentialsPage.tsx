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
  return (
    <Card className="panel wide-panel compact-panel">
      <Card.Header className="panel-header">
        <div className="panel-title">
          <KeyRound size={18} />
          <span>Credential Vault</span>
        </div>
        <div className="editor-actions">
          <span>{credentialStatus}</span>
          <Button size="sm" variant="secondary" onPress={onLoadCredentials}>
            <RefreshCw size={15} />
            Refresh
          </Button>
        </div>
      </Card.Header>
      <Card.Content className="panel-content">
        <form className="credential-form" onSubmit={onSubmitCredential}>
          <Input aria-label="Credential id" value={credentialId} onChange={(event) => onCredentialIdChange(event.target.value)} />
          <Input aria-label="Credential kind" value={credentialKind} onChange={(event) => onCredentialKindChange(event.target.value)} />
          <Input aria-label="Credential value" type="password" value={credentialValue} onChange={(event) => onCredentialValueChange(event.target.value)} />
          <select className="native-select" aria-label="Credential scope" value={credentialScope} onChange={(event) => onCredentialScopeChange(event.target.value as "global" | "agent")}>
            <option value="agent">agent</option>
            <option value="global">global</option>
          </select>
          <Button size="sm" variant="primary" type="submit">
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
