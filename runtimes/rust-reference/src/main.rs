use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};

fn main() -> std::io::Result<()> {
    let addr = std::env::var("ANYAGENT_RUST_REFERENCE_ADDR").unwrap_or_else(|_| "127.0.0.1:8799".to_string());
    let listener = TcpListener::bind(addr)?;
    for stream in listener.incoming() {
        handle(stream?)?;
    }
    Ok(())
}

fn handle(mut stream: TcpStream) -> std::io::Result<()> {
    let mut buf = [0_u8; 2048];
    let n = stream.read(&mut buf)?;
    let request = String::from_utf8_lossy(&buf[..n]);
    let mut parts = request.lines().next().unwrap_or_default().split_whitespace();
    let method = parts.next().unwrap_or_default();
    let path = parts.next().unwrap_or_default();
    let (status, body) = anyagent_rust_reference::route(method, path);
    write!(
        stream,
        "HTTP/1.1 {status}\r\ncontent-type: application/json\r\ncontent-length: {}\r\nconnection: close\r\n\r\n{body}",
        body.len()
    )
}
