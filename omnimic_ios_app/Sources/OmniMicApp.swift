import SwiftUI

@main
struct OmniMicApp: App {
    @StateObject private var discovery = StudioDiscovery()
    @StateObject private var audio = OmniMicAudioEngine()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(discovery)
                .environmentObject(audio)
                .preferredColorScheme(.dark)
        }
    }
}
