pub fn health_response() -> &'static str {
    r#"{"ok":true,"workspace":"rust-reference","agent_ids":["main"]}"#
}

pub fn credential_capabilities_response() -> &'static str {
    r#"{"resolver_modes":[],"admin_store_modes":[{"mode":"memory","display_name":"Rust reference memory store","kind":"admin_store","status":"preview","description":"Minimal Rust conformance target; not a production credential store.","supports_resolve":false,"supports_set":false,"supports_delete":false,"supports_list_refs":false,"read_only":true,"default_for":[],"requires_extras":[],"requires_env":[],"source":"runtimes/rust-reference"}],"environment_variable":"MCP_CREDENTIAL_STORE_BACKEND","secret_value_returned":false}"#
}

pub fn tool_catalog_response() -> &'static str {
    r#"{"toolset_version":"rust-reference:0","tools":[]}"#
}

pub fn route(method: &str, path: &str) -> (&'static str, &'static str) {
    match (method, path) {
        ("GET", "/healthz") => ("200 OK", health_response()),
        ("GET", "/admin/credentials/capabilities") => ("200 OK", credential_capabilities_response()),
        ("GET", "/admin/tools/catalog") => ("200 OK", tool_catalog_response()),
        _ => ("404 Not Found", r#"{"detail":"not found"}"#),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn exposes_health_contract() {
        let (status, body) = route("GET", "/healthz");
        assert_eq!(status, "200 OK");
        assert!(body.contains(r#""ok":true"#));
        assert!(body.contains(r#""agent_ids":["main"]"#));
    }

    #[test]
    fn exposes_admin_capability_contract_without_secret_values() {
        let (status, body) = route("GET", "/admin/credentials/capabilities");
        assert_eq!(status, "200 OK");
        assert!(body.contains(r#""secret_value_returned":false"#));
        assert!(!body.contains("secretValue"));
    }

    #[test]
    fn exposes_tool_catalog_contract() {
        let (status, body) = route("GET", "/admin/tools/catalog");
        assert_eq!(status, "200 OK");
        assert!(body.contains(r#""toolset_version":"rust-reference:0""#));
    }
}
