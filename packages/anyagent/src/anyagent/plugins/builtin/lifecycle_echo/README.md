# Lifecycle Echo Reference Plugin

This reference plugin demonstrates the public Plugin Manifest v1 contract:

- declares `manifest_version: "1"`
- registers one tool, `app.lifecycle_echo.echo`
- declares and implements `on_agent_start` and `on_agent_end`

It is inert until a server is started with a plugin root that contains this
directory, for example `anyagent serve --plugin-root <root>`.
