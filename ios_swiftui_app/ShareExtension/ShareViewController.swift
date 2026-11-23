import Darwin
import Foundation
import UIKit
import UniformTypeIdentifiers

/// Native iOS Share Extension ("Paylaş -> WinDrop")
/// Sends unlimited photos, videos, files, and URLs straight to Windows PC with zero compression.
final class ShareViewController: UIViewController {
    private let statusLabel = UILabel()
    private let progressView = UIProgressView(progressViewStyle: .default)
    private let cancelButton = UIButton(type: .system)
    private var cancelled = false

    override func viewDidLoad() {
        super.viewDidLoad()
        setupUI()
        Task { await runSharePipeline() }
    }

    private func setupUI() {
        view.backgroundColor = UIColor.black.withAlphaComponent(0.6)

        let card = UIView()
        card.backgroundColor = UIColor.secondarySystemBackground
        card.layer.cornerRadius = 22
        card.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(card)

        let titleLbl = UILabel()
        titleLbl.text = "⚡ WinDrop ➔ PC"
        titleLbl.font = .systemFont(ofSize: 18, weight: .bold)
        titleLbl.textAlignment = .center

        statusLabel.text = "Windows PC aranıyor..."
        statusLabel.font = .systemFont(ofSize: 13, weight: .medium)
        statusLabel.textColor = .secondaryLabel
        statusLabel.textAlignment = .center
        statusLabel.numberOfLines = 2

        progressView.progress = 0.05
        progressView.tintColor = .systemBlue

        cancelButton.setTitle("İptal", for: .normal)
        cancelButton.setTitleColor(.systemRed, for: .normal)
        cancelButton.titleLabel?.font = .systemFont(ofSize: 15, weight: .semibold)
        cancelButton.addTarget(self, action: #selector(didTapCancel), for: .touchUpInside)

        let stack = UIStackView(arrangedSubviews: [titleLbl, statusLabel, progressView, cancelButton])
        stack.axis = .vertical
        stack.spacing = 14
        stack.translatesAutoresizingMaskIntoConstraints = false
        card.addSubview(stack)

        NSLayoutConstraint.activate([
            card.centerYAnchor.constraint(equalTo: view.centerYAnchor),
            card.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 28),
            card.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -28),
            stack.topAnchor.constraint(equalTo: card.topAnchor, constant: 22),
            stack.bottomAnchor.constraint(equalTo: card.bottomAnchor, constant: -18),
            stack.leadingAnchor.constraint(equalTo: card.leadingAnchor, constant: 20),
            stack.trailingAnchor.constraint(equalTo: card.trailingAnchor, constant: -20),
        ])
    }

    @objc private func didTapCancel() {
        cancelled = true
        extensionContext?.completeRequest(returningItems: nil, completionHandler: nil)
    }

    private func resolvePCBaseURL() async -> String? {
        // 0. Check App Group shared host from main WinDrop app
        if let sharedBase = UserDefaults(suiteName: "group.com.tris.windrop.shared")?.string(forKey: "wd_last_base_url"),
           !sharedBase.isEmpty, await healthCheck(sharedBase) {
            return sharedBase
        }
        // 1. Try Bonjour hostname directly on LAN
        if await healthCheck("http://windrop.local:8765") {
            return "http://windrop.local:8765"
        }
        // 2. Try GitHub Pages live_endpoint.json (prefers LAN IP first, then Cloudflare tunnel)
        guard let mURL = URL(string: "https://mephisto-mert.github.io/windrop-ios/live_endpoint.json?t=\(Int(Date().timeIntervalSince1970))") else {
            return nil
        }
        var req = URLRequest(url: mURL, timeoutInterval: 4)
        req.cachePolicy = .reloadIgnoringLocalCacheData
        guard let (data, resp) = try? await URLSession.shared.data(for: req),
              let http = resp as? HTTPURLResponse, http.statusCode == 200,
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return nil
        }
        if let lanIP = json["lan_ip"] as? String, !lanIP.isEmpty {
            let port = json["port"] as? Int ?? 8765
            let lanURL = "http://\(lanIP):\(port)"
            if await healthCheck(lanURL) { return lanURL }
        }
        for key in ["primary", "url", "backup"] {
            if let t = json[key] as? String, t.hasPrefix("https://") {
                let clean = t.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
                if await healthCheck(clean) { return clean }
            }
        }
        return nil
    }

    private func healthCheck(_ base: String) async -> Bool {
        guard let u = URL(string: base + "/health") else { return false }
        var req = URLRequest(url: u, timeoutInterval: 2.2)
        req.httpMethod = "GET"
        guard let (_, resp) = try? await URLSession.shared.data(for: req),
              let http = resp as? HTTPURLResponse else { return false }
        return (200..<300).contains(http.statusCode)
    }

    private func runSharePipeline() async {
        guard let baseURL = await resolvePCBaseURL() else {
            await MainActor.run {
                statusLabel.text = "❌ Windows PC bulunamadı (WinDrop.exe açık mı?)"
            }
            try? await Task.sleep(nanoseconds: 1_800_000_000)
            extensionContext?.completeRequest(returningItems: nil, completionHandler: nil)
            return
        }

        let items = (extensionContext?.inputItems as? [NSExtensionItem]) ?? []
        let providers = items.flatMap { $0.attachments ?? [] }
        guard !providers.isEmpty else {
            extensionContext?.completeRequest(returningItems: nil, completionHandler: nil)
            return
        }

        var sentCount = 0
        for (index, provider) in providers.enumerated() {
            if cancelled { break }
            await MainActor.run {
                statusLabel.text = "(\(index + 1)/\(providers.count)) Gönderiliyor..."
                progressView.progress = Float(index) / Float(max(1, providers.count))
            }

            if provider.hasItemConformingToTypeIdentifier(UTType.fileURL.identifier) ||
               provider.hasItemConformingToTypeIdentifier(UTType.movie.identifier) ||
               provider.hasItemConformingToTypeIdentifier(UTType.image.identifier) ||
               provider.hasItemConformingToTypeIdentifier(UTType.data.identifier) {
                let typeId = provider.registeredTypeIdentifiers.first ?? UTType.item.identifier
                if let fileURL = await loadFileRepresentation(provider: provider, typeId: typeId) {
                    defer { try? FileManager.default.removeItem(at: fileURL) }
                    if (try? await uploadChunked(fileURL: fileURL, baseURL: baseURL)) != nil {
                        sentCount += 1
                    }
                }
            } else if provider.hasItemConformingToTypeIdentifier(UTType.url.identifier) {
                if let url = await loadWebURL(provider: provider) {
                    await sendURL(url.absoluteString, baseURL: baseURL)
                    sentCount += 1
                }
            }
        }

        await MainActor.run {
            progressView.progress = 1.0
            statusLabel.text = "✅ \(sentCount)/\(providers.count) öğe PC'ye kayıpsız gönderildi!"
        }
        try? await Task.sleep(nanoseconds: 900_000_000)
        extensionContext?.completeRequest(returningItems: nil, completionHandler: nil)
    }

    private func loadFileRepresentation(provider: NSItemProvider, typeId: String) async -> URL? {
        await withCheckedContinuation { cont in
            provider.loadFileRepresentation(forTypeIdentifier: typeId) { url, _ in
                guard let url = url else {
                    cont.resume(returning: nil)
                    return
                }
                let tmp = FileManager.default.temporaryDirectory
                    .appendingPathComponent("\(UUID().uuidString.prefix(8))_\(url.lastPathComponent)")
                try? FileManager.default.removeItem(at: tmp)
                do {
                    try FileManager.default.copyItem(at: url, to: tmp)
                    cont.resume(returning: tmp)
                } catch {
                    cont.resume(returning: nil)
                }
            }
        }
    }

    private func loadWebURL(provider: NSItemProvider) async -> URL? {
        await withCheckedContinuation { cont in
            provider.loadItem(forTypeIdentifier: UTType.url.identifier, options: nil) { item, _ in
                cont.resume(returning: item as? URL)
            }
        }
    }

    private func sendURL(_ urlStr: String, baseURL: String) async {
        guard let endpoint = URL(string: baseURL + "/api/open-url") else { return }
        var req = URLRequest(url: endpoint, timeoutInterval: 8)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try? JSONSerialization.data(withJSONObject: ["url": urlStr])
        _ = try? await URLSession.shared.data(for: req)
    }

    private func uploadChunked(fileURL: URL, baseURL: String) async throws {
        guard let endpoint = URL(string: baseURL + "/api/upload-chunk") else { throw URLError(.badURL) }
        let attrs = try FileManager.default.attributesOfItem(atPath: fileURL.path)
        let totalSize = (attrs[.size] as? NSNumber)?.int64Value ?? 0
        let handle = try FileHandle(forReadingFrom: fileURL)
        defer { try? handle.close() }

        let chunkSize = 8 * 1024 * 1024
        let uploadId = UUID().uuidString.replacingOccurrences(of: "-", with: "")
        let fileName = fileURL.lastPathComponent
        let encodedName = fileName.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? fileName
        var offset: Int64 = 0

        repeat {
            if cancelled { throw CancellationError() }
            let chunk = try handle.read(upToCount: chunkSize) ?? Data()
            let nextOffset = offset + Int64(chunk.count)
            let isLast = (nextOffset >= totalSize) || chunk.isEmpty

            var req = URLRequest(url: endpoint, timeoutInterval: 120)
            req.httpMethod = "POST"
            req.setValue("application/octet-stream", forHTTPHeaderField: "Content-Type")
            req.setValue(uploadId, forHTTPHeaderField: "X-Upload-Id")
            req.setValue(encodedName, forHTTPHeaderField: "X-File-Name")
            req.setValue(String(offset), forHTTPHeaderField: "X-Chunk-Offset")
            req.setValue(String(totalSize), forHTTPHeaderField: "X-Total-Size")
            req.setValue(isLast ? "1" : "0", forHTTPHeaderField: "X-Is-Last-Chunk")

            let (_, resp) = try await URLSession.shared.upload(for: req, from: chunk)
            guard let http = resp as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
                throw URLError(.badServerResponse)
            }
            offset = nextOffset
            if isLast { break }
        } while offset < totalSize
    }
}
