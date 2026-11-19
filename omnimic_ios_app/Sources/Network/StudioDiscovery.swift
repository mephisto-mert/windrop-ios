import Combine
import Darwin
import Foundation
import Network

public struct DiscoveredStudio: Identifiable, Hashable {
    public let id: String
    public let name: String
    public let baseURL: String
    public let via: String
    public let isTunnel: Bool

    public var url: URL? { URL(string: baseURL) }
}

@MainActor
public final class StudioDiscovery: NSObject, ObservableObject {
    @Published public var discoveredStudios: [DiscoveredStudio] = []
    @Published public var activeStudio: DiscoveredStudio?
    @Published public var statusText: String = "Wi-Fi & Bulut Stüdyo aranıyor..."
    @Published public var isSearching: Bool = false

    private let browser = NetServiceBrowser()
    private var resolving: [NetService] = []
    private let cloudManifestURL = "https://mephisto-mert.github.io/windrop-ios/omnimic/live_endpoint.json"

    public override init() {
        super.init()
        browser.delegate = self
        startDiscovery()
    }

    public func startDiscovery() {
        isSearching = true
        if activeStudio == nil {
            statusText = "Wi-Fi & Bulut Stüdyo aranıyor..."
        }
        browser.stop()
        resolving.removeAll()
        browser.searchForServices(ofType: "_omnimic._tcp.", inDomain: "local.")

        Task {
            await probeKnownEndpoints()
            isSearching = false
        }
    }

    public func probeKnownEndpoints() async {
        await withTaskGroup(of: Void.self) { group in
            if let saved = UserDefaults.standard.string(forKey: "om_manual_host"), !saved.trimmingCharacters(in: .whitespaces).isEmpty {
                let norm = normalizeBaseURL(saved)
                group.addTask {
                    await self.pingStudio(norm, via: "Kayıtlı IP", isTunnel: norm.hasPrefix("https://"))
                }
            }
            group.addTask {
                await self.pingStudio("http://omnimic.local:8125", via: "Bonjour (.local)", isTunnel: false)
            }
            group.addTask {
                await self.discoverFromCloudManifest()
            }
        }
        if activeStudio == nil {
            statusText = "🔴 PC bulunamadı (OmniMic Studio.exe açık mı?)"
        }
    }

    public func discoverFromCloudManifest() async {
        guard let url = URL(string: cloudManifestURL + "?t=\(Int(Date().timeIntervalSince1970))") else { return }
        var req = URLRequest(url: url, timeoutInterval: 4.5)
        req.cachePolicy = .reloadIgnoringLocalCacheData
        guard let (data, resp) = try? await URLSession.shared.data(for: req),
              let http = resp as? HTTPURLResponse, http.statusCode == 200,
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return
        }
        if let lanIP = json["lan_ip"] as? String, !lanIP.isEmpty {
            let port = json["port"] as? Int ?? 8125
            if await pingStudio("http://\(lanIP):\(port)", via: "Wi-Fi Otomatik", isTunnel: false) {
                return
            }
        }
        for key in ["primary", "url", "backup"] {
            if let t = json[key] as? String, t.hasPrefix("https://") {
                let clean = t.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
                if await pingStudio(clean, via: "Bulut Tüneli (4G/5G)", isTunnel: true) {
                    return
                }
            }
        }
    }

    @discardableResult
    public func pingStudio(_ rawBase: String, via: String, isTunnel: Bool) async -> Bool {
        let base = normalizeBaseURL(rawBase)
        guard let url = URL(string: base + "/api/telemetry") else { return false }
        var req = URLRequest(url: url, timeoutInterval: isTunnel ? 5.0 : 2.2)
        let tok = (UserDefaults.standard.string(forKey: "om_device_token") ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        if !tok.isEmpty {
            req.setValue(tok, forHTTPHeaderField: "X-OmniMic-Token")
        }
        do {
            let (_, resp) = try await URLSession.shared.data(for: req)
            guard let http = resp as? HTTPURLResponse,
                  (200..<300).contains(http.statusCode) || http.statusCode == 401 else {
                return false
            }
            let studio = DiscoveredStudio(
                id: base,
                name: isTunnel ? "OmniMic Bulut" : "OmniMic PC Stüdyo",
                baseURL: base,
                via: via,
                isTunnel: isTunnel
            )
            registerStudio(studio)
            return true
        } catch {
            return false
        }
    }

    public func connectManual(_ raw: String) async -> Bool {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return false }
        UserDefaults.standard.set(trimmed, forKey: "om_manual_host")
        let base = normalizeBaseURL(trimmed)
        let ok = await pingStudio(base, via: "Manuel Bağlantı", isTunnel: base.hasPrefix("https://"))
        if ok, let found = discoveredStudios.first(where: { $0.baseURL == base }) {
            activeStudio = found
            statusText = "🟢 Bağlandı: \(found.via)"
        } else {
            statusText = "🔴 Ulaşılamadı: \(base)"
        }
        return ok
    }

    private func studioPriority(_ s: DiscoveredStudio) -> Int {
        if s.isTunnel { return 1 }
        if s.baseURL.contains(".local") { return 2 }
        return 3
    }

    private func registerStudio(_ studio: DiscoveredStudio) {
        if let idx = discoveredStudios.firstIndex(where: { $0.baseURL == studio.baseURL || $0.name.caseInsensitiveCompare(studio.name) == .orderedSame }) {
            if studioPriority(studio) >= studioPriority(discoveredStudios[idx]) {
                discoveredStudios[idx] = studio
            }
        } else {
            discoveredStudios.append(studio)
        }
        let best = discoveredStudios.first(where: { $0.name.caseInsensitiveCompare(studio.name) == .orderedSame }) ?? studio
        if activeStudio == nil || studioPriority(best) >= studioPriority(activeStudio!) || activeStudio?.name.caseInsensitiveCompare(best.name) == .orderedSame {
            activeStudio = best
            statusText = "🟢 Bağlandı: \(best.name) • \(best.via)"
        }
    }

    public func normalizeBaseURL(_ raw: String) -> String {
        var s = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        while s.hasSuffix("/") { s.removeLast() }
        if !s.hasPrefix("http://") && !s.hasPrefix("https://") {
            s = s.contains(":") ? "http://\(s)" : "http://\(s):8125"
        }
        return s
    }

    public func stopDiscovery() {
        browser.stop()
        isSearching = false
    }
}

extension StudioDiscovery: NetServiceBrowserDelegate, NetServiceDelegate {
    nonisolated public func netServiceBrowser(_ browser: NetServiceBrowser, didFind service: NetService, moreComing: Bool) {
        Task { @MainActor in
            service.delegate = self
            self.resolving.append(service)
            service.resolve(withTimeout: 4.0)
        }
    }

    nonisolated public func netServiceDidResolveAddress(_ sender: NetService) {
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
        let port = sender.port > 0 ? sender.port : 8125
        Task { @MainActor in
            _ = await self.pingStudio("http://\(ip):\(port)", via: "Bonjour Wi-Fi", isTunnel: false)
        }
    }
}
