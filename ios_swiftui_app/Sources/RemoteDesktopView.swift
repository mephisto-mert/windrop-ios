import SwiftUI
import UIKit

// MARK: - WebSocket Stream Session

@MainActor
final class RemoteStreamSession: ObservableObject {
    @Published var currentFrame: UIImage?
    @Published var isStreaming: Bool = false
    @Published var fps: Int = 0
    @Published var rttMs: Int = 0
    @Published var profile: String = "balanced"

    private var wsTask: URLSessionWebSocketTask?
    private var receiveTask: Task<Void, Never>?
    private var pingTask: Task<Void, Never>?
    private var frameCounter: Int = 0
    private var lastFpsTick: CFTimeInterval = CFAbsoluteTimeGetCurrent()
    private var lastPingSent: CFTimeInterval = 0

    func connect(baseURL: String, token: String, profile: String) {
        disconnect()
        self.profile = profile
        let wsBase = baseURL
            .replacingOccurrences(of: "https://", with: "wss://")
            .replacingOccurrences(of: "http://", with: "ws://")
        var urlStr = "\(wsBase)/ws/remote/desktop?profile=\(profile)"
        let cleanTok = token.trimmingCharacters(in: .whitespacesAndNewlines)
        if !cleanTok.isEmpty, let enc = cleanTok.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) {
            urlStr += "&token=\(enc)"
        }
        guard let url = URL(string: urlStr) else { return }

        var req = URLRequest(url: url)
        if !cleanTok.isEmpty {
            req.setValue(cleanTok, forHTTPHeaderField: "X-WinDrop-Token")
        }
        let task = URLSession.shared.webSocketTask(with: req)
        self.wsTask = task
        self.isStreaming = true
        task.resume()

        receiveTask = Task { [weak self] in
            await self?.receiveLoop(task: task)
        }
        pingTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 2_000_000_000)
                await self?.sendPing()
            }
        }
    }

    func disconnect() {
        pingTask?.cancel()
        pingTask = nil
        receiveTask?.cancel()
        receiveTask = nil
        wsTask?.cancel(with: .goingAway, reason: nil)
        wsTask = nil
        isStreaming = false
    }

    func sendAction(_ payload: [String: Any]) {
        guard let task = wsTask,
              let data = try? JSONSerialization.data(withJSONObject: payload),
              let text = String(data: data, encoding: .utf8) else { return }
        task.send(.string(text)) { _ in }
    }

    private func sendPing() {
        lastPingSent = CFAbsoluteTimeGetCurrent()
        sendAction(["action": "ping", "t": lastPingSent * 1000.0])
    }

    private func receiveLoop(task: URLSessionWebSocketTask) async {
        while !Task.isCancelled {
            do {
                let message = try await task.receive()
                switch message {
                case .data(let data):
                    let decoded = await Task.detached(priority: .userInitiated) {
                        UIImage(data: data)
                    }.value
                    if let img = decoded {
                        self.currentFrame = img
                        self.frameCounter += 1
                        let now = CFAbsoluteTimeGetCurrent()
                        if now - self.lastFpsTick >= 1.0 {
                            self.fps = self.frameCounter
                            self.frameCounter = 0
                            self.lastFpsTick = now
                        }
                    }
                    task.send(.string("a")) { _ in }
                case .string(let txt):
                    if let d = txt.data(using: .utf8),
                       let obj = try? JSONSerialization.jsonObject(with: d) as? [String: Any],
                       (obj["action"] as? String) == "pong" {
                        let ms = Int(max(1, (CFAbsoluteTimeGetCurrent() - self.lastPingSent) * 1000.0))
                        self.rttMs = ms
                    }
                @unknown default:
                    break
                }
            } catch {
                self.isStreaming = false
                break
            }
        }
    }
}

// MARK: - AnyDesk-Style Native UIKeyInput Keyboard Proxy

final class AnyDeskKeyInputView: UIView, UIKeyInput {
    var onText: ((String) -> Void)?
    var onKey: ((String) -> Void)?
    var onCombo: ((String) -> Void)?
    var onClose: (() -> Void)?

    override var canBecomeFirstResponder: Bool { true }
    var hasText: Bool { true }

    var autocorrectionType: UITextAutocorrectionType = .no
    var autocapitalizationType: UITextAutocapitalizationType = .none
    var spellCheckingType: UITextSpellCheckingType = .no
    var keyboardAppearance: UIKeyboardAppearance = .dark

    private lazy var accessoryBar: UIView = {
        let bar = UIView(frame: CGRect(x: 0, y: 0, width: UIScreen.main.bounds.width, height: 44))
        bar.backgroundColor = UIColor(white: 0.11, alpha: 0.96)

        let scroll = UIScrollView()
        scroll.showsHorizontalScrollIndicator = false
        scroll.translatesAutoresizingMaskIntoConstraints = false
        bar.addSubview(scroll)

        let stack = UIStackView()
        stack.axis = .horizontal
        stack.spacing = 6
        stack.alignment = .center
        stack.translatesAutoresizingMaskIntoConstraints = false
        scroll.addSubview(stack)

        NSLayoutConstraint.activate([
            scroll.topAnchor.constraint(equalTo: bar.topAnchor),
            scroll.bottomAnchor.constraint(equalTo: bar.bottomAnchor),
            scroll.leadingAnchor.constraint(equalTo: bar.leadingAnchor, constant: 6),
            scroll.trailingAnchor.constraint(equalTo: bar.trailingAnchor, constant: -6),
            stack.topAnchor.constraint(equalTo: scroll.topAnchor, constant: 4),
            stack.bottomAnchor.constraint(equalTo: scroll.bottomAnchor, constant: -4),
            stack.leadingAnchor.constraint(equalTo: scroll.leadingAnchor),
            stack.trailingAnchor.constraint(equalTo: scroll.trailingAnchor),
            stack.heightAnchor.constraint(equalTo: scroll.heightAnchor, constant: -8),
        ])

        let keys: [(String, String, UIColor)] = [
            ("✕ Kapat", "__close__", .systemRed),
            ("Esc", "escape", .secondarySystemFill),
            ("Tab", "tab", .secondarySystemFill),
            ("Ctrl+C", "ctrl+c", UIColor.systemBlue.withAlphaComponent(0.35)),
            ("Ctrl+V", "ctrl+v", UIColor.systemBlue.withAlphaComponent(0.35)),
            ("Alt+Tab", "alt+tab", UIColor.systemGreen.withAlphaComponent(0.35)),
            ("Win+D", "win+d", UIColor.systemBlue.withAlphaComponent(0.35)),
            ("◀", "left", .secondarySystemFill),
            ("▲", "up", .secondarySystemFill),
            ("▼", "down", .secondarySystemFill),
            ("▶", "right", .secondarySystemFill),
            ("Görev Yön.", "ctrl+shift+escape", UIColor.systemOrange.withAlphaComponent(0.35)),
        ]

        for (title, code, bg) in keys {
            let btn = UIButton(type: .system)
            btn.setTitle(title, for: .normal)
            btn.setTitleColor(.white, for: .normal)
            btn.titleLabel?.font = .systemFont(ofSize: 12, weight: .semibold)
            btn.backgroundColor = bg
            btn.layer.cornerRadius = 8
            btn.contentEdgeInsets = UIEdgeInsets(top: 6, left: 10, bottom: 6, right: 10)
            btn.addAction(UIAction { [weak self] _ in
                if code == "__close__" {
                    self?.resignFirstResponder()
                    self?.onClose?()
                } else if code.contains("+") {
                    self?.onCombo?(code)
                } else {
                    self?.onKey?(code)
                }
            }, for: .touchUpInside)
            stack.addArrangedSubview(btn)
        }
        return bar
    }()

    override var inputAccessoryView: UIView? { accessoryBar }

    func insertText(_ text: String) {
        if text == "\n" {
            onKey?("enter")
        } else if !text.isEmpty {
            onText?(text)
        }
    }

    func deleteBackward() {
        onKey?("backspace")
    }
}

struct AnyDeskKeyboardBridge: UIViewRepresentable {
    @Binding var isActive: Bool
    var onText: (String) -> Void
    var onKey: (String) -> Void
    var onCombo: (String) -> Void

    func makeUIView(context: Context) -> AnyDeskKeyInputView {
        let view = AnyDeskKeyInputView(frame: .zero)
        view.backgroundColor = .clear
        view.onText = onText
        view.onKey = onKey
        view.onCombo = onCombo
        view.onClose = {
            DispatchQueue.main.async { isActive = false }
        }
        return view
    }

    func updateUIView(_ uiView: AnyDeskKeyInputView, context: Context) {
        uiView.onText = onText
        uiView.onKey = onKey
        uiView.onCombo = onCombo
        if isActive {
            if !uiView.isFirstResponder {
                DispatchQueue.main.async { uiView.becomeFirstResponder() }
            }
        } else {
            if uiView.isFirstResponder {
                DispatchQueue.main.async { uiView.resignFirstResponder() }
            }
        }
    }
}

// MARK: - Interactive Remote Touch Canvas (Safe-Area Respecting)

final class RemoteCanvasUIView: UIView, UIGestureRecognizerDelegate {
    let imageView = UIImageView()
    var trackpadMode: Bool = false
    var onAction: (([String: Any]) -> Void)?
    var onDismissKeyboard: (() -> Void)?

    private var lastPanPoint: CGPoint = .zero
    private var lastScrollPoint: CGPoint = .zero
    private var isDraggingLeft: Bool = false

    override init(frame: CGRect) {
        super.init(frame: frame)
        backgroundColor = .black
        imageView.contentMode = .scaleAspectFit
        imageView.frame = bounds
        imageView.autoresizingMask = [.flexibleWidth, .flexibleHeight]
        addSubview(imageView)

        let doubleTap = UITapGestureRecognizer(target: self, action: #selector(handleDoubleTap(_:)))
        doubleTap.numberOfTapsRequired = 2
        addGestureRecognizer(doubleTap)

        let singleTap = UITapGestureRecognizer(target: self, action: #selector(handleSingleTap(_:)))
        singleTap.numberOfTapsRequired = 1
        singleTap.require(toFail: doubleTap)
        addGestureRecognizer(singleTap)

        let longPress = UILongPressGestureRecognizer(target: self, action: #selector(handleLongPress(_:)))
        longPress.minimumPressDuration = 0.45
        addGestureRecognizer(longPress)

        let pan1 = UIPanGestureRecognizer(target: self, action: #selector(handleOneFingerPan(_:)))
        pan1.minimumNumberOfTouches = 1
        pan1.maximumNumberOfTouches = 1
        pan1.delegate = self
        addGestureRecognizer(pan1)

        let pan2 = UIPanGestureRecognizer(target: self, action: #selector(handleTwoFingerScroll(_:)))
        pan2.minimumNumberOfTouches = 2
        pan2.maximumNumberOfTouches = 2
        pan2.delegate = self
        addGestureRecognizer(pan2)
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    private func normalizedPoint(for point: CGPoint) -> (Double, Double)? {
        guard let img = imageView.image, img.size.width > 0, img.size.height > 0 else { return nil }
        let vw = imageView.bounds.width
        let vh = imageView.bounds.height
        guard vw > 0, vh > 0 else { return nil }

        let imgAspect = img.size.width / img.size.height
        let viewAspect = vw / vh
        let renderRect: CGRect
        if viewAspect > imgAspect {
            let rw = vh * imgAspect
            renderRect = CGRect(x: (vw - rw) / 2.0, y: 0, width: rw, height: vh)
        } else {
            let rh = vw / imgAspect
            renderRect = CGRect(x: 0, y: (vh - rh) / 2.0, width: vw, height: rh)
        }
        let nx = max(0.0, min(1.0, (point.x - renderRect.minX) / max(1.0, renderRect.width)))
        let ny = max(0.0, min(1.0, (point.y - renderRect.minY) / max(1.0, renderRect.height)))
        return (Double(nx), Double(ny))
    }

    @objc private func handleSingleTap(_ gr: UITapGestureRecognizer) {
        onDismissKeyboard?()
        if trackpadMode {
            onAction?(["action": "touch_click", "button": "left"])
            return
        }
        let pt = gr.location(in: imageView)
        if let (nx, ny) = normalizedPoint(for: pt) {
            onAction?(["action": "touch_click", "button": "left", "x_pct": nx, "y_pct": ny])
        }
    }

    @objc private func handleDoubleTap(_ gr: UITapGestureRecognizer) {
        onDismissKeyboard?()
        if trackpadMode {
            onAction?(["action": "double_click", "button": "left"])
            return
        }
        let pt = gr.location(in: imageView)
        if let (nx, ny) = normalizedPoint(for: pt) {
            onAction?(["action": "double_click", "button": "left", "x_pct": nx, "y_pct": ny])
        }
    }

    @objc private func handleLongPress(_ gr: UILongPressGestureRecognizer) {
        guard gr.state == .began else { return }
        UIImpactFeedbackGenerator(style: .medium).impactOccurred()
        if trackpadMode {
            onAction?(["action": "touch_click", "button": "right"])
            return
        }
        let pt = gr.location(in: imageView)
        if let (nx, ny) = normalizedPoint(for: pt) {
            onAction?(["action": "touch_click", "button": "right", "x_pct": nx, "y_pct": ny])
        }
    }

    @objc private func handleOneFingerPan(_ gr: UIPanGestureRecognizer) {
        let pt = gr.location(in: imageView)
        if trackpadMode {
            switch gr.state {
            case .began:
                lastPanPoint = pt
            case .changed:
                let dx = Int(round((pt.x - lastPanPoint.x) * 2.1))
                let dy = Int(round((pt.y - lastPanPoint.y) * 2.1))
                if dx != 0 || dy != 0 {
                    lastPanPoint = pt
                    onAction?(["action": "mouse_delta", "dx": dx, "dy": dy])
                }
            default:
                break
            }
            return
        }

        guard let (nx, ny) = normalizedPoint(for: pt) else { return }
        switch gr.state {
        case .began:
            isDraggingLeft = true
            onAction?(["action": "mouse_down", "button": "left", "x_pct": nx, "y_pct": ny])
        case .changed:
            if isDraggingLeft {
                onAction?(["action": "mouse_move", "x_pct": nx, "y_pct": ny])
            }
        case .ended, .cancelled, .failed:
            if isDraggingLeft {
                isDraggingLeft = false
                onAction?(["action": "mouse_up", "button": "left", "x_pct": nx, "y_pct": ny])
            }
        default:
            break
        }
    }

    @objc private func handleTwoFingerScroll(_ gr: UIPanGestureRecognizer) {
        let pt = gr.location(in: imageView)
        switch gr.state {
        case .began:
            lastScrollPoint = pt
        case .changed:
            let dx = Int(round(-(pt.x - lastScrollPoint.x) * 2.2))
            let dy = Int(round(-(pt.y - lastScrollPoint.y) * 2.2))
            if abs(dx) > 1 || abs(dy) > 1 {
                lastScrollPoint = pt
                onAction?(["action": "scroll", "dx": dx, "dy": dy])
            }
        default:
            break
        }
    }
}

struct RemoteTouchCanvas: UIViewRepresentable {
    var frameImage: UIImage?
    var trackpadMode: Bool
    var onAction: ([String: Any]) -> Void
    var onDismissKeyboard: () -> Void

    func makeUIView(context: Context) -> RemoteCanvasUIView {
        let v = RemoteCanvasUIView()
        v.trackpadMode = trackpadMode
        v.onAction = onAction
        v.onDismissKeyboard = onDismissKeyboard
        return v
    }

    func updateUIView(_ uiView: RemoteCanvasUIView, context: Context) {
        uiView.imageView.image = frameImage
        uiView.trackpadMode = trackpadMode
        uiView.onAction = onAction
        uiView.onDismissKeyboard = onDismissKeyboard
    }
}

// MARK: - Main Remote Desktop Screen (Zero Top Clutter + Safe-Area Clickable)

struct RemoteDesktopView: View {
    @ObservedObject var client: WinDropClient
    @StateObject private var stream = RemoteStreamSession()

    @State private var trackpadMode: Bool = false
    @State private var keyboardOpen: Bool = false
    @State private var showControlsSheet: Bool = false
    @State private var selectedProfile: String = "balanced"

    var body: some View {
        ZStack(alignment: .bottomTrailing) {
            Color.black.ignoresSafeArea()

            // Respects iOS Safe Areas (Dynamic Island & Home Bar) so top & bottom edges are 100% clickable!
            if client.activePeer != nil {
                RemoteTouchCanvas(
                    frameImage: stream.currentFrame,
                    trackpadMode: trackpadMode,
                    onAction: { action in
                        stream.sendAction(action)
                    },
                    onDismissKeyboard: {
                        if keyboardOpen { keyboardOpen = false }
                    }
                )
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                VStack(spacing: 14) {
                    Image(systemName: "desktopcomputer.trianglebadge.exclamationmark")
                        .font(.system(size: 46))
                        .foregroundColor(.gray)
                    Text("Bağlı PC Bulunamadı")
                        .font(.headline)
                        .foregroundColor(.white)
                    Button("Yeniden Ara") {
                        client.startDiscovery()
                    }
                    .buttonStyle(.borderedProminent)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }

            // Hidden Native UIKeyInput Keyboard Bridge
            AnyDeskKeyboardBridge(
                isActive: $keyboardOpen,
                onText: { txt in stream.sendAction(["action": "type_text", "text": txt]) },
                onKey: { key in stream.sendAction(["action": "key_press", "key": key]) },
                onCombo: { combo in stream.sendAction(["action": "key_combo", "keys": combo]) }
            )
            .frame(width: 1, height: 1)
            .allowsHitTesting(false)

            // Unobtrusive Bottom-Right AnyDesk Floating Action Cluster (No Top Bars!)
            HStack(spacing: 10) {
                Button {
                    keyboardOpen.toggle()
                } label: {
                    Image(systemName: keyboardOpen ? "keyboard.chevron.compact.down" : "keyboard")
                        .font(.system(size: 16, weight: .semibold))
                        .foregroundColor(.white)
                        .frame(width: 40, height: 40)
                        .background(keyboardOpen ? Color.blue.opacity(0.85) : Color.black.opacity(0.55))
                        .clipShape(Circle())
                        .overlay(Circle().stroke(Color.white.opacity(0.22), lineWidth: 1))
                }

                Button {
                    showControlsSheet = true
                } label: {
                    Image(systemName: "bolt.fill")
                        .font(.system(size: 16, weight: .semibold))
                        .foregroundColor(.white)
                        .frame(width: 40, height: 40)
                        .background(Color.black.opacity(0.55))
                        .clipShape(Circle())
                        .overlay(Circle().stroke(Color.white.opacity(0.22), lineWidth: 1))
                }
            }
            .padding(.trailing, 14)
            .padding(.bottom, 14)
        }
        .onAppear {
            startStreamIfReady()
        }
        .onDisappear {
            keyboardOpen = false
            stream.disconnect()
        }
        .onChange(of: client.activePeer) { _ in
            startStreamIfReady()
        }
        .sheet(isPresented: $showControlsSheet) {
            remoteSettingsSheet
                .presentationDetents([.medium])
                .presentationDragIndicator(.visible)
        }
    }

    private func startStreamIfReady() {
        guard let peer = client.activePeer else { return }
        let prof = peer.isTunnel ? "fast" : selectedProfile
        stream.connect(baseURL: peer.baseURL, token: client.deviceToken, profile: prof)
    }

    private var remoteSettingsSheet: some View {
        NavigationView {
            List {
                Section("Bağlantı & Akış") {
                    HStack {
                        Text("Durum")
                        Spacer()
                        Text(stream.isStreaming ? "🟢 \(stream.fps) FPS • \(stream.rttMs)ms" : "🔴 Bağlı Değil")
                            .foregroundColor(stream.isStreaming ? .green : .red)
                    }
                    Picker("Kalite Profili", selection: $selectedProfile) {
                        Text("Akıcı (720p)").tag("fast")
                        Text("Dengeli (1080p)").tag("balanced")
                        Text("Ultra (2K)").tag("ultra")
                    }
                    .pickerStyle(.segmented)
                    .onChange(of: selectedProfile) { newProf in
                        stream.sendAction(["action": "set_profile", "profile": newProf])
                    }
                }

                Section("Kontrol & Gizlilik") {
                    Toggle("İztopu (Trackpad) Modu", isOn: $trackpadMode)

                    Button {
                        let nextIdx = (client.activeMonitorIndex % max(1, client.monitorCount)) + 1
                        client.activeMonitorIndex = nextIdx
                        stream.sendAction(["action": "set_monitor", "index": nextIdx])
                    } label: {
                        Label("Monitör Değiştir (Aktif: \(client.activeMonitorIndex)/\(client.monitorCount))", systemImage: "display.2")
                    }

                    Button {
                        Task { await client.toggleHostMute() }
                    } label: {
                        Label(client.hostMuted ? "PC Hoparlörünü Aç" : "PC Hoparlörünü Sustur", systemImage: client.hostMuted ? "speaker.wave.2.fill" : "speaker.slash.fill")
                            .foregroundColor(client.hostMuted ? .orange : .primary)
                    }

                    Button {
                        Task { await client.togglePrivacyCurtain() }
                    } label: {
                        Label(client.privacyEnabled ? "Gizlilik Ekranını Kapat" : "Gizlilik Ekranı (PC Monitörü Karart)", systemImage: client.privacyEnabled ? "eye.fill" : "eye.slash.fill")
                            .foregroundColor(client.privacyEnabled ? .green : .primary)
                    }
                }

                Section("Medya & Kısayollar") {
                    HStack(spacing: 12) {
                        Button("⏯️") { stream.sendAction(["action": "key_press", "key": "media_play_pause"]) }
                        Button("🔉") { stream.sendAction(["action": "key_press", "key": "volume_down"]) }
                        Button("🔊") { stream.sendAction(["action": "key_press", "key": "volume_up"]) }
                        Button("Alt+Tab") { stream.sendAction(["action": "key_combo", "keys": "alt+tab"]) }
                        Button("Win+D") { stream.sendAction(["action": "key_combo", "keys": "win+d"]) }
                    }
                    .buttonStyle(.bordered)
                }
            }
            .navigationTitle("Uzak Masaüstü")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Bitti") { showControlsSheet = false }
                }
            }
        }
    }
}
