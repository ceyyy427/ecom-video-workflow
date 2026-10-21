// Offline Apple Vision OCR. Inputs are local audit thumbnails, never user code.
import Foundation
import Vision

var frames = [[String: Any]]()
guard CommandLine.arguments.count >= 3 else { exit(2) }
for path in CommandLine.arguments.dropFirst(2).prefix(12) {
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.recognitionLanguages = ["zh-Hans", "en-US"]
    request.usesLanguageCorrection = false
    do {
        try VNImageRequestHandler(url: URL(fileURLWithPath: path), options: [:]).perform([request])
        let texts: [[String: Any]] = (request.results ?? []).prefix(80).compactMap { observation in
            guard let top = observation.topCandidates(1).first else { return nil }
            let box = observation.boundingBox
            return ["text": String(top.string.prefix(500)), "confidence": top.confidence,
                    "box": [box.origin.x, box.origin.y, box.size.width, box.size.height]]
        }
        frames.append(["texts": texts])
    } catch {
        frames.append(["error": "本机Vision未完成此帧识别", "texts": [[String: Any]]()])
    }
}
let data = try JSONSerialization.data(withJSONObject: ["frames": frames], options: [.sortedKeys])
try data.write(to: URL(fileURLWithPath: CommandLine.arguments[1]), options: .atomic)
