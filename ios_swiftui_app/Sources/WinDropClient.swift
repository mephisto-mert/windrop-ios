import ActivityKit
import CoreTransferable
import Darwin
import Foundation
import Photos
import SwiftUI
import UIKit
import UniformTypeIdentifiers

// MARK: - Models

struct WinDropPeer: Identifiable, Hashable {
    let id: String
    let name: String
    let baseURL: String
    let via: String
    let isTunnel: Bool
    var macAddress: String = ""
}

struct SavedPeerRecord: Identifiable, Codable, Hashable {
    let id: String
    let name: String
    let baseURL: String
    let macAddress: String
}

struct OutboundFileItem: Identifiable, Decodable {
    let id: String
    let name: String
    let size: Int64
}

struct ClipboardHistoryItem: Identifiable, Decodable {
    let id: String
    let text: String
    let source: String?
    let time: String?
}

struct TransferRecord: Identifiable {
    let id = UUID()
    let fileName: String
    let sizeBytes: Int64
    let direction: String
    let detail: String
    let isSuccess: Bool
}

/// Preserves original raw file bytes on disk (HEIC, DNG, 4K HDR MOV) with zero re-encoding or RAM spikes.
struct LosslessMediaFile: Transferable {
    let url: URL

    static var transferRepresentation: some TransferRepresentation {
        FileRepresentation(importedContentType: .item) { received in
            let tmpDir = FileManager.default.temporaryDirectory
                .appendingPathComponent("windrop_picker", isDirectory: true)
            try? FileManager.default.createDirectory(at: tmpDir, withIntermediateDirectories: true)
            let origName = received.file.lastPathComponent
            let dest = tmpDir.appendingPathComponent("\(UUID().uuidString.prefix(8))_\(origName)")
            try? FileManager.default.removeItem(at: dest)
            try FileManager.default.copyItem(at: received.file, to: dest)
            return Self(url: dest)
        }
    }
}

// MARK: - Main WinDrop Native Client

@MainActor
final class WinDropClient: NSObject, ObservableObject {
    @Published var discoveredPeers: [WinDropPeer] = []
    @Published var savedPeers: [SavedPeerRecord] = []
    @Published var wakingPeerName: String = ""
    @Published var updateStatus: String = "v4.0.0 • Güncel"
    @Published var updateAvailableURL: String = ""
    @Published var activePeer: WinDropPeer?
    @Published var connectionStatus: String = "Yerel ağda PC aranıyor..."
    @Published var isConnected: Bool = false

    // Upload Queue State (Unlimited)
    @Published var isUploading: Bool = false
    @Published var uploadFileName: String = ""
    @Published var uploadProgress: Double = 0.0
    @Published var uploadSpeedMBps: Double = 0.0
    @Published var uploadDoneCount: Int = 0
    @Published var uploadTotalCount: Int = 0

    // Outbound (PC -> iPhone) & History
    @Published var outboundFiles: [OutboundFileItem] = []
    @Published var history: [TransferRecord] = []

    // Clipboard
    @Published var pcClipboardText: String = ""
    @Published var clipboardHistory: [ClipboardHistoryItem] = []
    @Published var pcClipboardImage: UIImage?

    // Remote Status
    @Published var hostMuted: Bool = false
    @Published var privacyEnabled: Bool = false
    @Published var activeMonitorIndex: Int = 1
    @Published var monitorCount: Int = 1
    @Published var isRemoteFullscreen: Bool = false
    @Published var quickLookURL: URL?

    private let sharedDefaults = UserDefaults(suiteName: "group.com.tris.windrop.shared")

    // Persistent Settings
    @Published var manualHost: String {
        didSet { UserDefaults.standard.set(manualHost, forKey: "wd_manual_host") }
    }
    @Published var deviceToken: String {
        didSet { UserDefaults.standard.set(deviceToken, forKey: "wd_device_token") }
    }

    private let browserHttp = NetServiceBrowser()
    private let browserWinDrop = NetServiceBrowser()
    private var resolvingServices: [NetService] = []
    private var uploadQueue: [(url: URL, cleanupAfter: Bool)] = []
    private var uploadCancelled = false
    private var currentActivityRef: Any?
    private var autoDownloadedIds: Set<String> = []
    private var outboundPollTask: Task<Void, Never>?
    private let tunnelManifestURL = "https://mephisto-mert.github.io/windrop-ios/live_endpoint.json"

    override init() {
        self.manualHost = UserDefaults.standard.string(forKey: "wd_manual_host") ?? ""
        self.deviceToken = UserDefaults.standard.string(forKey: "wd_device_token") ?? ""
        if let data = UserDefaults.standard.data(forKey: "wd_saved_peers"),
           let decoded = try? JSONDecoder().decode([SavedPeerRecord].self, from: data) {
            self.savedPeers = decoded
        }
        super.init()
        browserHttp.delegate = self
        browserWinDrop.delegate = self
        startDiscovery()
        startOutboundAutoWatcher()
        Task { await checkAppUpdate() }
    }

    private func startOutboundAutoWatcher() {
        outboundPollTask?.cancel()
        outboundPollTask = Task {
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 2_500_000_000)
                if activePeer != nil {
                    await fetchOutboundFiles(autoDownloadNew: true)
                }
            }
        }
    }

    func checkAppUpdate() async {
        updateStatus = "Kontrol ediliyor..."
        guard let url = URL(string: "https://api.github.com/repos/mephisto-mert/windrop-ios/releases/latest") else {
            updateStatus = "v4.0.0 • Güncel"
            return
        }
        var req = URLRequest(url: url, timeoutInterval: 6)
        req.setValue("WinDrop-iOS/4.0", forHTTPHeaderField: "User-Agent")
        guard let (data, resp) = try? await URLSession.shared.data(for: req),
              let http = resp as? HTTPURLResponse, http.statusCode == 200,
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let tag = json["tag_name"] as? String else {
            updateStatus = "v4.0.0 • Güncel"
            return
        }
        let cleanTag = tag.trimmingCharacters(in: CharacterSet(charactersIn: "vV"))
        if cleanTag.compare("4.0.0", options: .numeric) == .orderedDescending {
            updateStatus = "Yeni sürüm mevcut: v\(cleanTag)"
            updateAvailableURL = (json["html_url"] as? String) ?? "https://mephisto-mert.github.io/windrop-ios/apps.json"
        } else {
            updateStatus = "v4.0.0 • Güncel"
            updateAvailableURL = ""
        }
    }

    var offlineSavedPeers: [SavedPeerRecord] {
        savedPeers.filter { saved in
            !discoveredPeers.contains(where: { $0.name.caseInsensitiveCompare(saved.name) == .orderedSame })
        }
    }

    func savePeerForWoL(name: String, baseURL: String, mac: String) {
        let rec = SavedPeerRecord(id: name.lowercased(), name: name, baseURL: baseURL, macAddress: mac)
        if let idx = savedPeers.firstIndex(where: { $0.id == rec.id }) {
            savedPeers[idx] = rec
        } else {
            savedPeers.append(rec)
        }
        if let data = try? JSONEncoder().encode(savedPeers) {
            UserDefaults.standard.set(data, forKey: "wd_saved_peers")
        }
        sharedDefaults?.set(baseURL, forKey: "wd_last_base_url")
    }

    func removeSavedPeer(_ saved: SavedPeerRecord) {
        savedPeers.removeAll { $0.id == saved.id }
        if let data = try? JSONEncoder().encode(savedPeers) {
            UserDefaults.standard.set(data, forKey: "wd_saved_peers")
        }
    }

    func sendWakeOnLan(to saved: SavedPeerRecord) {
        let hexChars = saved.macAddress.filter { $0.isHexDigit }
        guard hexChars.count == 12 else { return }
        var macBytes: [UInt8] = []
        var idx = hexChars.startIndex
        for _ in 0..<6 {
            let next = hexChars.index(idx, offsetBy: 2)
            if let b = UInt8(hexChars[idx..<next], radix: 16) {
                macBytes.append(b)
            }
            idx = next
        }
        guard macBytes.count == 6 else { return }

        var packet = [UInt8](repeating: 0xFF, count: 6)
        for _ in 0..<16 { packet.append(contentsOf: macBytes) }

        wakingPeerName = saved.name
        connectionStatus = "⚡ \(saved.name) uyandırılıyor (WoL)..."

        DispatchQueue.global(qos: .userInitiated).async {
            let sock = Darwin.socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP)
            if sock >= 0 {
                var broadcast: Int32 = 1
                setsockopt(sock, SOL_SOCKET, SO_BROADCAST, &broadcast, socklen_t(MemoryLayout<Int32>.size))
                var addr = sockaddr_in()
                addr.sin_family = sa_family_t(AF_INET)
                addr.sin_port = UInt16(9).bigEndian
                addr.sin_addr.s_addr = inet_addr("255.255.255.255")
                let len = socklen_t(MemoryLayout<sockaddr_in>.size)
                packet.withUnsafeBytes { ptr in
                    withUnsafePointer(to: &addr) {
                        $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { sa in
                            _ = Darwin.sendto(sock, ptr.baseAddress, packet.count, 0, sa, len)
                        }
                    }
                }
                Darwin.close(sock)
            }
        }

        Task {
            for _ in 0..<8 {
                try? await Task.sleep(nanoseconds: 2_000_000_000)
                if await connectManualHost(saved.baseURL) {
                    wakingPeerName = ""
                    return
                }
            }
            wakingPeerName = ""
        }
    }

    // MARK: - Discovery (Bonjour mDNS + Saved Host + Cloudflare Tunnel)

    func startDiscovery() {
        if activePeer == nil {
            connectionStatus = "Wi-Fi & Bulut PC aranıyor..."
        }
        browserHttp.stop()
        browserWinDrop.stop()
        resolvingServices.removeAll()
        browserHttp.searchForServices(ofType: "_http._tcp.", inDomain: "local.")
        browserWinDrop.searchForServices(ofType: "_windrop._tcp.", inDomain: "local.")

        Task {
            await probeKnownEndpoints()
        }
    }

    func probeKnownEndpoints() async {
        // 1. Try saved manual LAN host first
        let saved = manualHost.trimmingCharacters(in: .whitespacesAndNewlines)
        if !saved.isEmpty {
            let normalized = normalizeBaseURL(saved)
            if await pingEndpoint(normalized, via: "Kayıtlı IP", isTunnel: normalized.hasPrefix("https://")) {
                return
            }
        }
        // 2. Try windrop.local:8765 (Bonjour hostname)
        if await pingEndpoint("http://windrop.local:8765", via: "Bonjour (.local)", isTunnel: false) {
            return
        }
        // 3. Fallback to live Cloudflare Tunnel / LAN IP from GitHub Pages manifest
        await discoverFromCloudManifest()
    }

    func discoverFromCloudManifest() async {
        guard let url = URL(string: tunnelManifestURL + "?t=\(Int(Date().timeIntervalSince1970))") else { return }
        var req = URLRequest(url: url, timeoutInterval: 5)
        req.cachePolicy = .reloadIgnoringLocalCacheData
        guard let (data, resp) = try? await URLSession.shared.data(for: req),
              let http = resp as? HTTPURLResponse, http.statusCode == 200,
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return
        }

        // Prefer LAN IP reported in manifest if reachable on same Wi-Fi
        if let lanIP = json["lan_ip"] as? String, !lanIP.isEmpty {
            let port = json["port"] as? Int ?? 8765
            let lanURL = "http://\(lanIP):\(port)"
            if await pingEndpoint(lanURL, via: "Wi-Fi Otomatik", isTunnel: false) {
                return
            }
        }
        // Otherwise connect via Cloudflare Tunnel (4G/5G)
        for key in ["primary", "url", "backup"] {
            if let tUrl = json[key] as? String, tUrl.hasPrefix("https://") {
                let clean = tUrl.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
                if await pingEndpoint(clean, via: "Bulut Tüneli (4G/5G)", isTunnel: true) {
                    return
                }
            }
        }
    }

    @discardableResult
    func pingEndpoint(_ rawBase: String, via: String, isTunnel: Bool) async -> Bool {
        let base = normalizeBaseURL(rawBase)
        guard let url = URL(string: base + "/health") else { return false }
        var req = makeRequest(url: url, timeout: isTunnel ? 5.0 : 2.2)
        req.httpMethod = "GET"
        do {
            let (data, resp) = try await URLSession.shared.data(for: req)
            guard let http = resp as? HTTPURLResponse, (200..<300).contains(http.statusCode) else { return false }
            var name = "Windows PC"
            var mac = ""
            if let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                if let pcName = json["pc_name"] as? String, !pcName.isEmpty {
                    name = pcName
                }
                if let macStr = json["mac"] as? String, !macStr.isEmpty {
                    mac = macStr
                }
            }
            let peer = WinDropPeer(id: base, name: name, baseURL: base, via: via, isTunnel: isTunnel, macAddress: mac)
            if !mac.isEmpty && !isTunnel {
                savePeerForWoL(name: name, baseURL: base, mac: mac)
            }
            registerPeer(peer, selectIfBetter: true)
            return true
        } catch {
            return false
        }
    }

    func connectManualHost(_ host: String) async -> Bool {
        manualHost = host.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !manualHost.isEmpty else { return false }
        let base = normalizeBaseURL(manualHost)
        let ok = await pingEndpoint(base, via: "Manuel Bağlantı", isTunnel: base.hasPrefix("https://"))
        if ok {
            if let peer = discoveredPeers.first(where: { $0.baseURL == base }) {
                activePeer = peer
                isConnected = true
                connectionStatus = "🟢 Bağlandı: \(peer.name) (\(peer.via))"
                await refreshAll()
            }
        } else {
            connectionStatus = "🔴 Bağlanılamadı: \(base)"
        }
        return ok
    }

    func selectPeer(_ peer: WinDropPeer) {
        activePeer = peer
        isConnected = true
        connectionStatus = "🟢 \(peer.name) • \(peer.via)"
        Task { await refreshAll() }
    }

    func handleDeepLink(_ url: URL) {
        guard let comps = URLComponents(url: url, resolvingAgainstBaseURL: false) else { return }
        if let tok = comps.queryItems?.first(where: { $0.name == "token" })?.value, !tok.isEmpty {
            deviceToken = tok
        }
        if let host = comps.queryItems?.first(where: { $0.name == "host" })?.value, !host.isEmpty {
            Task { _ = await connectManualHost(host) }
        }
    }

    private func peerPriority(_ peer: WinDropPeer) -> Int {
        if peer.isTunnel { return 1 }
        if peer.baseURL.contains(".local") { return 2 }
        return 3 // Direct LAN IP is fastest & most reliable
    }

    private func registerPeer(_ peer: WinDropPeer, selectIfBetter: Bool) {
        if let idx = discoveredPeers.firstIndex(where: { $0.baseURL == peer.baseURL || $0.name.caseInsensitiveCompare(peer.name) == .orderedSame }) {
            let existing = discoveredPeers[idx]
            if peerPriority(peer) >= peerPriority(existing) {
                discoveredPeers[idx] = peer
            }
        } else {
            discoveredPeers.append(peer)
        }
        let best = discoveredPeers.first(where: { $0.name.caseInsensitiveCompare(peer.name) == .orderedSame }) ?? peer
        if selectIfBetter {
            if activePeer == nil || peerPriority(best) >= peerPriority(activePeer!) || activePeer?.name.caseInsensitiveCompare(best.name) == .orderedSame {
                activePeer = best
                isConnected = true
                connectionStatus = "🟢 Bağlandı: \(best.name) • \(best.via)"
                Task { await refreshAll() }
            }
        } else if let cur = activePeer {
            isConnected = true
            connectionStatus = "🟢 Bağlandı: \(cur.name) • \(cur.via)"
        }
    }

    func normalizeBaseURL(_ raw: String) -> String {
        var s = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        while s.hasSuffix("/") { s.removeLast() }
        if !s.hasPrefix("http://") && !s.hasPrefix("https://") {
            if s.contains(":") {
                s = "http://" + s
            } else {
                s = "http://" + s + ":8765"
            }
        }
        return s
    }

    func makeRequest(url: URL, method: String = "GET", timeout: TimeInterval = 30) -> URLRequest {
        var req = URLRequest(url: url, timeoutInterval: timeout)
        req.httpMethod = method
        let tok = deviceToken.trimmingCharacters(in: .whitespacesAndNewlines)
        if !tok.isEmpty {
            req.setValue(tok, forHTTPHeaderField: "X-WinDrop-Token")
        }
        req.setValue(UIDevice.current.name, forHTTPHeaderField: "X-Device-Model")
        return req
    }

    func refreshAll() async {
        await fetchOutboundFiles()
        await fetchClipboard()
        await fetchMonitors()
    }

    // MARK: - Unlimited Lossless 8 MB Chunked Upload Queue

    func enqueueFiles(_ urls: [URL], cleanupAfter: Bool) {
        guard !urls.isEmpty else { return }
        uploadCancelled = false
        for u in urls {
            uploadQueue.append((url: u, cleanupAfter: cleanupAfter))
        }
        uploadTotalCount += urls.count
        if !isUploading {
            Task { await processUploadQueue() }
        }
    }

    func cancelUploads() {
        uploadCancelled = true
        uploadQueue.removeAll()
        isUploading = false
        uploadDoneCount = 0
        uploadTotalCount = 0
        connectionStatus = "⛔ Aktarım iptal edildi"
    }

    private func processUploadQueue() async {
        guard let peer = activePeer else {
            connectionStatus = "⚠️ Önce bir PC seçin veya bağlanın"
            uploadQueue.removeAll()
            uploadTotalCount = 0
            uploadDoneCount = 0
            return
        }
        isUploading = true
        var bgTask: UIBackgroundTaskIdentifier = .invalid
        bgTask = UIApplication.shared.beginBackgroundTask(withName: "WinDropUpload") {
            UIApplication.shared.endBackgroundTask(bgTask)
            bgTask = .invalid
        }
        startLiveActivity(pcName: peer.name, fileName: uploadQueue.first?.url.lastPathComponent ?? "Dosya", totalCount: uploadTotalCount)
        defer {
            isUploading = false
            endLiveActivity(pcName: peer.name, fileName: uploadFileName, doneCount: uploadDoneCount, totalCount: uploadTotalCount)
            uploadTotalCount = 0
            uploadDoneCount = 0
            if bgTask != .invalid {
                UIApplication.shared.endBackgroundTask(bgTask)
                bgTask = .invalid
            }
        }

        while !uploadQueue.isEmpty && !uploadCancelled {
            let item = uploadQueue.removeFirst()
            uploadDoneCount += 1
            let fileURL = item.url
            let fileName = fileURL.lastPathComponent
            uploadFileName = fileName
            uploadProgress = 0.0

            let accessed = fileURL.startAccessingSecurityScopedResource()
            defer {
                if accessed { fileURL.stopAccessingSecurityScopedResource() }
                if item.cleanupAfter { try? FileManager.default.removeItem(at: fileURL) }
            }

            do {
                let attrs = try FileManager.default.attributesOfItem(atPath: fileURL.path)
                let totalSize = (attrs[.size] as? NSNumber)?.int64Value ?? 0
                try await uploadFileChunked(fileURL: fileURL, fileName: fileName, totalSize: totalSize, baseURL: peer.baseURL)
                history.insert(
                    TransferRecord(
                        fileName: fileName,
                        sizeBytes: totalSize,
                        direction: "iPhone ➔ PC",
                        detail: "Kayıpsız (\(String(format: "%.1f", uploadSpeedMBps)) MB/sn)",
                        isSuccess: true
                    ),
                    at: 0
                )
            } catch {
                if uploadCancelled { break }
                history.insert(
                    TransferRecord(
                        fileName: fileName,
                        sizeBytes: 0,
                        direction: "iPhone ➔ PC",
                        detail: "Hata: \(error.localizedDescription)",
                        isSuccess: false
                    ),
                    at: 0
                )
            }
        }
    }

    private func uploadFileChunked(fileURL: URL, fileName: String, totalSize: Int64, baseURL: String) async throws {
        guard let endpoint = URL(string: baseURL + "/api/upload-chunk") else {
            throw URLError(.badURL)
        }
        let handle = try FileHandle(forReadingFrom: fileURL)
        defer { try? handle.close() }

        let chunkSize = 8 * 1024 * 1024 // 8 MB lossless slices
        let uploadId = UUID().uuidString.replacingOccurrences(of: "-", with: "")
        let encodedName = fileName.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? fileName
        var offset: Int64 = 0
        let startTime = CFAbsoluteTimeGetCurrent()

        repeat {
            if uploadCancelled { throw CancellationError() }
            let chunk = try handle.read(upToCount: chunkSize) ?? Data()
            let nextOffset = offset + Int64(chunk.count)
            let isLast = (nextOffset >= totalSize) || chunk.isEmpty

            var req = makeRequest(url: endpoint, method: "POST", timeout: 120)
            req.setValue("application/octet-stream", forHTTPHeaderField: "Content-Type")
            req.setValue(uploadId, forHTTPHeaderField: "X-Upload-Id")
            req.setValue(encodedName, forHTTPHeaderField: "X-File-Name")
            req.setValue(String(offset), forHTTPHeaderField: "X-Chunk-Offset")
            req.setValue(String(totalSize), forHTTPHeaderField: "X-Total-Size")
            req.setValue(isLast ? "1" : "0", forHTTPHeaderField: "X-Is-Last-Chunk")

            let (_, resp) = try await URLSession.shared.upload(for: req, from: chunk)
            guard let http = resp as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
                let code = (resp as? HTTPURLResponse)?.statusCode ?? -1
                throw NSError(domain: "WinDrop", code: code, userInfo: [NSLocalizedDescriptionKey: "HTTP \(code)"])
            }

            offset = nextOffset
            let elapsed = max(CFAbsoluteTimeGetCurrent() - startTime, 0.05)
            uploadSpeedMBps = (Double(offset) / 1_048_576.0) / elapsed
            uploadProgress = totalSize > 0 ? min(1.0, Double(offset) / Double(totalSize)) : 1.0
            updateLiveActivity(fileName: fileName, progress: uploadProgress, speedMBps: uploadSpeedMBps, doneCount: uploadDoneCount, totalCount: uploadTotalCount)
            if isLast { break }
        } while offset < totalSize
    }

    // MARK: - Dynamic Island / Live Activity Helpers

    private func startLiveActivity(pcName: String, fileName: String, totalCount: Int) {
        guard #available(iOS 16.2, *), ActivityAuthorizationInfo().areActivitiesEnabled else { return }
        let attr = TransferActivityAttributes(pcName: pcName)
        let state = TransferActivityAttributes.ContentState(
            fileName: fileName, progress: 0.0, speedMBps: 0.0, doneCount: 0, totalCount: totalCount, isCompleted: false
        )
        if let act = try? Activity<TransferActivityAttributes>.request(attributes: attr, contentState: state, pushType: nil) {
            currentActivityRef = act
        }
    }

    private func updateLiveActivity(fileName: String, progress: Double, speedMBps: Double, doneCount: Int, totalCount: Int) {
        guard #available(iOS 16.2, *), let act = currentActivityRef as? Activity<TransferActivityAttributes> else { return }
        let state = TransferActivityAttributes.ContentState(
            fileName: fileName, progress: progress, speedMBps: speedMBps, doneCount: doneCount, totalCount: totalCount, isCompleted: false
        )
        Task { await act.update(using: state) }
    }

    private func endLiveActivity(pcName: String, fileName: String, doneCount: Int, totalCount: Int) {
        guard #available(iOS 16.2, *), let act = currentActivityRef as? Activity<TransferActivityAttributes> else { return }
        let finalState = TransferActivityAttributes.ContentState(
            fileName: fileName.isEmpty ? "Tamamlandı" : fileName,
            progress: 1.0,
            speedMBps: uploadSpeedMBps,
            doneCount: doneCount,
            totalCount: max(1, totalCount),
            isCompleted: true
        )
        Task { await act.end(using: finalState, dismissalPolicy: .after(.now + 4)) }
        currentActivityRef = nil
    }

    // MARK: - Outbound PC -> iPhone Files

    func fetchOutboundFiles(autoDownloadNew: Bool = false) async {
        guard let peer = activePeer, let url = URL(string: peer.baseURL + "/api/outbound/files") else { return }
        let req = makeRequest(url: url, timeout: 6)
        guard let (data, resp) = try? await URLSession.shared.data(for: req),
              let http = resp as? HTTPURLResponse, http.statusCode == 200 else { return }
        if let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let filesArr = json["files"] as? [[String: Any]] {
            let parsed = filesArr.compactMap { dict -> OutboundFileItem? in
                guard let id = dict["id"] as? String, let name = dict["name"] as? String else { return nil }
                let size = (dict["size"] as? NSNumber)?.int64Value ?? 0
                return OutboundFileItem(id: id, name: name, size: size)
            }
            outboundFiles = parsed
            if autoDownloadNew {
                for item in parsed where !autoDownloadedIds.contains(item.id) {
                    autoDownloadedIds.insert(item.id)
                    let msg = await downloadAndSaveOutbound(item)
                    history.insert(TransferRecord(fileName: item.name, sizeBytes: item.size, direction: "PC ➔ iPhone", detail: msg, isSuccess: !msg.hasPrefix("❌")), at: 0)
                }
            } else {
                for item in parsed { autoDownloadedIds.insert(item.id) }
            }
        }
    }

    func downloadAndSaveOutbound(_ item: OutboundFileItem) async -> String {
        guard let peer = activePeer, let url = URL(string: peer.baseURL + "/api/download/\(item.id)") else {
            return "Bağlantı yok"
        }
        let req = makeRequest(url: url, timeout: 300)
        do {
            let (tmpURL, resp) = try await URLSession.shared.download(for: req)
            guard let http = resp as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
                return "İndirme başarısız"
            }
            let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first!
            let dest = docs.appendingPathComponent(item.name)
            try? FileManager.default.removeItem(at: dest)
            try FileManager.default.moveItem(at: tmpURL, to: dest)
            quickLookURL = dest
            UINotificationFeedbackGenerator().notificationOccurred(.success)

            let ext = dest.pathExtension.lowercased()
            let isPhoto = ["heic", "heif", "jpg", "jpeg", "png", "dng", "webp"].contains(ext)
            let isVideo = ["mov", "mp4", "m4v"].contains(ext)

            if isPhoto || isVideo {
                let status = await PHPhotoLibrary.requestAuthorization(for: .addOnly)
                if status == .authorized || status == .limited {
                    try await PHPhotoLibrary.shared().performChanges {
                        let creation = PHAssetCreationRequest.forAsset()
                        creation.addResource(with: isVideo ? .video : .photo, fileURL: dest, options: nil)
                    }
                    history.insert(TransferRecord(fileName: item.name, sizeBytes: item.size, direction: "PC ➔ iPhone", detail: "Galeri'ye kayıpsız kaydedildi", isSuccess: true), at: 0)
                    return "✅ Galeri'ye kaydedildi"
                }
            }
            history.insert(TransferRecord(fileName: item.name, sizeBytes: item.size, direction: "PC ➔ iPhone", detail: "Dosyalar'a kaydedildi", isSuccess: true), at: 0)
            return "📂 Dosyalar'a kaydedildi"
        } catch {
            return "❌ Hata: \(error.localizedDescription)"
        }
    }

    // MARK: - Universal Clipboard (Text + Image + Open URL)

    func fetchClipboard() async {
        guard let peer = activePeer, let url = URL(string: peer.baseURL + "/api/clipboard") else { return }
        let req = makeRequest(url: url, timeout: 6)
        guard let (data, resp) = try? await URLSession.shared.data(for: req),
              let http = resp as? HTTPURLResponse, http.statusCode == 200,
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return }
        pcClipboardText = (json["text"] as? String) ?? ""
        if let histArr = json["history"] as? [[String: Any]] {
            clipboardHistory = histArr.compactMap { d in
                guard let txt = d["text"] as? String else { return nil }
                return ClipboardHistoryItem(
                    id: (d["id"] as? String) ?? UUID().uuidString,
                    text: txt,
                    source: d["source"] as? String,
                    time: d["time"] as? String
                )
            }
        }
    }

    func pushClipboardText(_ text: String) async -> Bool {
        guard let peer = activePeer, let url = URL(string: peer.baseURL + "/api/clipboard") else { return false }
        var req = makeRequest(url: url, method: "POST", timeout: 8)
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try? JSONSerialization.data(withJSONObject: ["text": text, "source": UIDevice.current.name])
        guard let (_, resp) = try? await URLSession.shared.data(for: req),
              let http = resp as? HTTPURLResponse, (200..<300).contains(http.statusCode) else { return false }
        pcClipboardText = text
        await fetchClipboard()
        return true
    }

    func fetchClipboardImage() async {
        guard let peer = activePeer, let url = URL(string: peer.baseURL + "/api/clipboard/image") else { return }
        let req = makeRequest(url: url, timeout: 10)
        guard let (data, resp) = try? await URLSession.shared.data(for: req),
              let http = resp as? HTTPURLResponse else { return }
        if http.statusCode == 200, let img = UIImage(data: data) {
            pcClipboardImage = img
        } else {
            pcClipboardImage = nil
        }
    }

    func openURLOnPC(_ rawURL: String) async -> Bool {
        guard let peer = activePeer, let url = URL(string: peer.baseURL + "/api/open-url") else { return false }
        var req = makeRequest(url: url, method: "POST", timeout: 8)
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try? JSONSerialization.data(withJSONObject: ["url": rawURL])
        guard let (_, resp) = try? await URLSession.shared.data(for: req),
              let http = resp as? HTTPURLResponse, (200..<300).contains(http.statusCode) else { return false }
        return true
    }

    // MARK: - Remote PC Helpers (Monitors, Mute, Privacy)

    func fetchMonitors() async {
        guard let peer = activePeer, let url = URL(string: peer.baseURL + "/api/remote/monitors") else { return }
        let req = makeRequest(url: url, timeout: 5)
        guard let (data, resp) = try? await URLSession.shared.data(for: req),
              let http = resp as? HTTPURLResponse, http.statusCode == 200,
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return }
        if let idx = json["active_index"] as? Int { activeMonitorIndex = idx }
        if let mons = json["monitors"] as? [[String: Any]], !mons.isEmpty { monitorCount = mons.count }
    }

    func toggleHostMute() async {
        guard let peer = activePeer, let url = URL(string: peer.baseURL + "/api/remote/audio/mute") else { return }
        var req = makeRequest(url: url, method: "POST", timeout: 6)
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = Data("{}".utf8)
        guard let (data, resp) = try? await URLSession.shared.data(for: req),
              let http = resp as? HTTPURLResponse, http.statusCode == 200,
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let m = json["muted"] as? Bool else { return }
        hostMuted = m
    }

    func togglePrivacyCurtain() async {
        guard let peer = activePeer, let url = URL(string: peer.baseURL + "/api/remote/privacy") else { return }
        var req = makeRequest(url: url, method: "POST", timeout: 6)
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = Data("{}".utf8)
        guard let (data, resp) = try? await URLSession.shared.data(for: req),
              let http = resp as? HTTPURLResponse, http.statusCode == 200,
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let en = json["enabled"] as? Bool else { return }
        privacyEnabled = en
    }

    func sendRemoteActionHTTP(_ payload: [String: Any]) async {
        guard let peer = activePeer, let url = URL(string: peer.baseURL + "/api/remote/action") else { return }
        var req = makeRequest(url: url, method: "POST", timeout: 5)
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try? JSONSerialization.data(withJSONObject: payload)
        _ = try? await URLSession.shared.data(for: req)
    }
}

// MARK: - Bonjour (mDNS) Delegate

extension WinDropClient: NetServiceBrowserDelegate, NetServiceDelegate {
    nonisolated func netServiceBrowser(_ browser: NetServiceBrowser, didFind service: NetService, moreComing: Bool) {
        let lower = service.name.lowercased()
        guard lower.contains("windrop") || service.type.contains("_windrop") else { return }
        Task { @MainActor in
            service.delegate = self
            self.resolvingServices.append(service)
            service.resolve(withTimeout: 4.0)
        }
    }

    nonisolated func netServiceDidResolveAddress(_ sender: NetService) {
        guard let addrs = sender.addresses else { return }
        var resolvedIP: String?
        for data in addrs {
            data.withUnsafeBytes { rawPtr in
                guard let base = rawPtr.baseAddress else { return }
                let sa = base.assumingMemoryBound(to: sockaddr.self).pointee
                if sa.sa_family == UInt8(AF_INET) {
                    var sin = base.assumingMemoryBound(to: sockaddr_in.self).pointee
                    var buf = [CChar](repeating: 0, count: Int(INET_ADDRSTRLEN))
                    if inet_ntop(AF_INET, &sin.sin_addr, &buf, socklen_t(INET_ADDRSTRLEN)) != nil {
                        let ip = String(cString: buf)
                        if !ip.hasPrefix("127.") && !ip.hasPrefix("169.254.") {
                            resolvedIP = ip
                        }
                    }
                }
            }
            if resolvedIP != nil { break }
        }
        guard let ip = resolvedIP else { return }
        let port = sender.port > 0 ? sender.port : 8765
        let baseURL = "http://\(ip):\(port)"
        Task { @MainActor in
            _ = await self.pingEndpoint(baseURL, via: "Bonjour Wi-Fi", isTunnel: false)
        }
    }
}
