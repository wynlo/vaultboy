#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::net::TcpStream;
use std::sync::Mutex;
use std::time::Duration;

use tauri::{Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_shell::process::CommandChild;
use tauri_plugin_shell::ShellExt;

struct Backend(Mutex<Option<CommandChild>>);

fn backend_port() -> u16 {
    let Ok(home) = std::env::var("HOME") else {
        return 4567;
    };
    let path = std::path::Path::new(&home).join(".vaultboy").join("config.json");
    std::fs::read_to_string(path)
        .ok()
        .and_then(|text| serde_json::from_str::<serde_json::Value>(&text).ok())
        .and_then(|value| value.get("port").and_then(|port| port.as_u64()))
        .map(|port| port as u16)
        .unwrap_or(4567)
}

fn port_alive(port: u16) -> bool {
    TcpStream::connect_timeout(&([127, 0, 0, 1], port).into(), Duration::from_millis(300)).is_ok()
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(Backend(Mutex::new(None)))
        .setup(|app| {
            let port = backend_port();
            // If a Vaultboy backend is already running (e.g. dev mode or the
            // launchd agent), attach to it instead of spawning a second one.
            if !port_alive(port) {
                let sidecar = app
                    .shell()
                    .sidecar("vaultboy-backend")?
                    .env("VAULTBOY_SIDECAR", "1");
                let (mut rx, child) = sidecar.spawn()?;
                app.state::<Backend>().0.lock().unwrap().replace(child);
                // Drain sidecar output so the event channel never backs up.
                tauri::async_runtime::spawn(async move {
                    while rx.recv().await.is_some() {}
                });
            }
            let handle = app.handle().clone();
            std::thread::spawn(move || {
                for _ in 0..120 {
                    if port_alive(port) {
                        break;
                    }
                    std::thread::sleep(Duration::from_millis(250));
                }
                let url = format!("http://127.0.0.1:{port}")
                    .parse()
                    .expect("valid backend url");
                let window_handle = handle.clone();
                let _ = handle.run_on_main_thread(move || {
                    WebviewWindowBuilder::new(&window_handle, "main", WebviewUrl::External(url))
                        .title("Vaultboy")
                        .inner_size(1100.0, 800.0)
                        .min_inner_size(420.0, 600.0)
                        .build()
                        .expect("failed to create window");
                });
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building Vaultboy")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                if let Some(child) = app.state::<Backend>().0.lock().unwrap().take() {
                    let _ = child.kill();
                }
            }
        });
}
