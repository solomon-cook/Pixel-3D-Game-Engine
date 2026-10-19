// Minimal host reference for the engine's macOS minimization check.
// Build/run on macOS with:
//   xcrun swiftc scripts/appkit_minimize_reference.swift -o /tmp/appkit-minimize-reference
//   /tmp/appkit-minimize-reference
import AppKit
import Darwin

let app = NSApplication.shared
app.setActivationPolicy(.regular)

let window = NSWindow(
    contentRect: NSRect(x: 200, y: 200, width: 640, height: 400),
    styleMask: [.titled, .closable, .miniaturizable, .resizable],
    backing: .buffered,
    defer: false
)
window.title = "AppKit Minimize Reference"
window.center()
window.makeKeyAndOrderFront(nil)
app.activate(ignoringOtherApps: true)

var minimizedByEitherMethod = false
DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) {
    let precondition = [
        "application_active": app.isActive,
        "window_key": window.isKeyWindow,
        "window_visible": window.isVisible,
        "window_miniaturizable": window.isMiniaturizable,
        "minimize_button_enabled": window.standardWindowButton(.miniaturizeButton)?.isEnabled ?? false,
    ]
    let before = window.isMiniaturized

    window.miniaturize(nil)
    DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) {
        let afterMiniaturize = window.isMiniaturized
        if !afterMiniaturize {
            window.performMiniaturize(nil)
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) {
            let afterPerform = window.isMiniaturized
            minimizedByEitherMethod = afterMiniaturize || afterPerform
            let result: [String: Any] = [
                "macos_version": ProcessInfo.processInfo.operatingSystemVersionString,
                "precondition": precondition,
                "before": before,
                "after_miniaturize": afterMiniaturize,
                "after_perform_miniaturize": afterPerform,
                "verified": minimizedByEitherMethod,
            ]
            if let data = try? JSONSerialization.data(withJSONObject: result, options: [.sortedKeys]),
               let output = String(data: data, encoding: .utf8) {
                print(output)
                fflush(stdout)
            }
            app.terminate(nil)
        }
    }
}

app.run()
exit(minimizedByEitherMethod ? 0 : 1)
