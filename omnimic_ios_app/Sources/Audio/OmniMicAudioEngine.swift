import AVFoundation
import Combine
import Foundation

@MainActor
public final class OmniMicAudioEngine: ObservableObject {
    @Published public var isTransmitting: Bool = false
    @Published public var currentRmsDb: Float = -100.0
    @Published public var currentPeakDb: Float = -100.0
    @Published public var isMuted: Bool = false
    @Published public var isRecording: Bool = false
    @Published public var activeProfile: String = "warm_podcast"
    @Published public var denoiseEnabled: Bool = true
    @Published public var deesserEnabled: Bool = true
    @Published public var antiHowlingEnabled: Bool = false
    @Published public var masterGain: Double = 1.0
    @Published public var deviceToken: String {
        didSet { UserDefaults.standard.set(deviceToken, forKey: "om_device_token") }
    }

    private let audioEngine = AVAudioEngine()
    private var webSocketTask: URLSessionWebSocketTask?
    private var session = URLSession(configuration: .default)
    private var activeBaseURL: String = ""

    public init() {
        self.deviceToken = UserDefaults.standard.string(forKey: "om_device_token") ?? ""
        configureAudioSession()
    }

    private func configureAudioSession() {
        let audioSession = AVAudioSession.sharedInstance()
        do {
            try audioSession.setCategory(
                .playAndRecord,
                mode: .voiceChat,
                options: [.defaultToSpeaker, .allowBluetooth, .allowBluetoothA2DP]
            )
            try audioSession.setPreferredSampleRate(48000.0)
            try audioSession.setPreferredIOBufferDuration(0.005)
            try audioSession.setActive(true, options: .notifyOthersOnDeactivation)
        } catch {
            print("Audio Session config error: \(error)")
        }
    }

    public func startStreaming(to studio: DiscoveredStudio) {
        guard !isTransmitting else { return }
        activeBaseURL = studio.baseURL
        configureAudioSession()

        let wsBase = studio.baseURL
            .replacingOccurrences(of: "https://", with: "wss://")
            .replacingOccurrences(of: "http://", with: "ws://")
        var wsStr = "\(wsBase)/ws/audio"
        let tok = deviceToken.trimmingCharacters(in: .whitespacesAndNewlines)
        if !tok.isEmpty, let enc = tok.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) {
            wsStr += "?token=\(enc)"
        }
        guard let wsUrl = URL(string: wsStr) else { return }

        var req = URLRequest(url: wsUrl)
        if !tok.isEmpty {
            req.setValue(tok, forHTTPHeaderField: "X-OmniMic-Token")
        }
        webSocketTask = session.webSocketTask(with: req)
        webSocketTask?.resume()

        let inputNode = audioEngine.inputNode
        let hwFormat = inputNode.outputFormat(forBus: 0)
        let targetFormat = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 48000, channels: 1, interleaved: false)
        let converter = targetFormat.flatMap { AVAudioConverter(from: hwFormat, to: $0) }

        inputNode.installTap(onBus: 0, bufferSize: 512, format: hwFormat) { [weak self] buffer, _ in
            guard let self = self else { return }
            let sendBuf: AVAudioPCMBuffer
            if let conv = converter, let outFmt = targetFormat, hwFormat.sampleRate != 48000 || hwFormat.channelCount != 1 {
                let cap = AVAudioFrameCount(Double(buffer.frameLength) * (48000.0 / max(1.0, hwFormat.sampleRate)) + 16)
                guard let converted = AVAudioPCMBuffer(pcmFormat: outFmt, frameCapacity: cap) else { return }
                var err: NSError?
                var supplied = false
                conv.convert(to: converted, error: &err) { _, outStatus in
                    if supplied {
                        outStatus.pointee = .noDataNow
                        return nil
                    }
                    supplied = true
                    outStatus.pointee = .haveData
                    return buffer
                }
                sendBuf = converted
            } else {
                sendBuf = buffer
            }

            guard let channelData = sendBuf.floatChannelData?[0] else { return }
            let frameLength = Int(sendBuf.frameLength)
            guard frameLength > 0 else { return }

            var sum: Float = 0.0
            var maxVal: Float = 0.0
            for i in 0..<frameLength {
                let s = channelData[i]
                sum += s * s
                let a = abs(s)
                if a > maxVal { maxVal = a }
            }
            let rms = sqrt(sum / Float(frameLength))
            let rmsDb = max(-100.0, 20.0 * log10(max(1e-5, rms)))
            let peakDb = max(-100.0, 20.0 * log10(max(1e-5, maxVal)))

            Task { @MainActor in
                self.currentRmsDb = rmsDb
                self.currentPeakDb = peakDb
                guard self.isTransmitting, !self.isMuted else { return }
                var pcm16Data = Data(count: frameLength * 2)
                pcm16Data.withUnsafeMutableBytes { rawBuffer in
                    let pcm16 = rawBuffer.bindMemory(to: Int16.self)
                    for i in 0..<frameLength {
                        let clamped = max(-1.0, min(1.0, channelData[i]))
                        pcm16[i] = Int16(clamped * 32767.0)
                    }
                }
                self.webSocketTask?.send(.data(pcm16Data)) { _ in }
            }
        }

        do {
            try audioEngine.start()
            isTransmitting = true
        } catch {
            print("Audio Engine start error: \(error)")
        }
    }

    public func stopStreaming() {
        guard isTransmitting else { return }
        audioEngine.inputNode.removeTap(onBus: 0)
        audioEngine.stop()
        webSocketTask?.cancel(with: .goingAway, reason: nil)
        webSocketTask = nil
        isTransmitting = false
        currentRmsDb = -100.0
        currentPeakDb = -100.0
    }

    public func toggleMute() {
        isMuted.toggle()
        Task { await postAPI("/api/mute/toggle", body: [:]) }
    }

    public func toggleRecord() {
        isRecording.toggle()
        Task { await postAPI("/api/record/toggle", body: [:]) }
    }

    public func setProfile(_ profile: String) {
        activeProfile = profile
        Task { await postAPI("/api/profile", body: ["profile": profile]) }
    }

    public func syncDSP() {
        Task {
            await postAPI("/api/dsp", body: [
                "spectral_denoise": denoiseEnabled,
                "deesser": deesserEnabled,
                "anti_howling": antiHowlingEnabled,
            ])
        }
    }

    public func setGain(_ val: Double) {
        masterGain = val
        Task { await postAPI("/api/gain", body: ["gain": val]) }
    }

    public func playSound(_ name: String) {
        Task { await postAPI("/api/soundboard", body: ["sound": name]) }
    }

    private func postAPI(_ path: String, body: [String: Any]) async {
        guard !activeBaseURL.isEmpty, let url = URL(string: activeBaseURL + path) else { return }
        var req = URLRequest(url: url, timeoutInterval: 5)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let tok = deviceToken.trimmingCharacters(in: .whitespacesAndNewlines)
        if !tok.isEmpty {
            req.setValue(tok, forHTTPHeaderField: "X-OmniMic-Token")
        }
        req.httpBody = try? JSONSerialization.data(withJSONObject: body)
        _ = try? await URLSession.shared.data(for: req)
    }
}
