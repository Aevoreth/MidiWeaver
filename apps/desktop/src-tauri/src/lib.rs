use std::net::TcpStream;
use std::sync::Mutex;
use std::time::Duration;

use tauri::{Emitter, Manager, State};
use tauri_plugin_shell::process::CommandEvent;
use tauri_plugin_shell::ShellExt;

const DEFAULT_ENGINE_PORT: u16 = 8765;

struct EngineState {
    url: String,
}

#[tauri::command]
fn get_engine_url(state: State<'_, Mutex<EngineState>>) -> Result<String, String> {
    state
        .lock()
        .map(|s| s.url.clone())
        .map_err(|e| e.to_string())
}

fn wait_for_port(port: u16, attempts: u32) -> bool {
    for _ in 0..attempts {
        if TcpStream::connect(("127.0.0.1", port)).is_ok() {
            return true;
        }
        std::thread::sleep(Duration::from_millis(250));
    }
    false
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            let port = DEFAULT_ENGINE_PORT;
            let url = format!("http://127.0.0.1:{port}");

            #[cfg(not(debug_assertions))]
            {
                match app.shell().sidecar("midiweaver-engine") {
                    Ok(sidecar) => {
                        let port_arg = port.to_string();
                        match sidecar.args(["--port", &port_arg, "--host", "127.0.0.1"]).spawn() {
                            Ok((mut rx, _child)) => {
                                let app_handle = app.handle().clone();
                                let health_url = url.clone();
                                tauri::async_runtime::spawn(async move {
                                    while let Some(event) = rx.recv().await {
                                        if let CommandEvent::Terminated(payload) = event {
                                            eprintln!(
                                                "MidiWeaver engine sidecar exited: {:?}",
                                                payload
                                            );
                                        }
                                    }
                                    let _ = app_handle.emit("engine-sidecar-exited", ());
                                });

                                if wait_for_port(port, 40) {
                                    let _ = app.emit("engine-ready", health_url.clone());
                                } else {
                                    eprintln!(
                                        "Engine sidecar did not respond on {health_url}/health"
                                    );
                                }
                            }
                            Err(err) => eprintln!("Failed to spawn engine sidecar: {err}"),
                        }
                    }
                    Err(err) => eprintln!(
                        "Engine sidecar binary missing (build with PyInstaller): {err}"
                    ),
                }
            }

            #[cfg(debug_assertions)]
            {
                let _ = app.emit("engine-ready", url.clone());
            }

            app.manage(Mutex::new(EngineState { url }));
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![get_engine_url])
        .run(tauri::generate_context!())
        .expect("error while running MidiWeaver");
}
