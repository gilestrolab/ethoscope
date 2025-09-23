#!/usr/bin/env python3
"""
Ethoscope Camera IR Optimization Test Script

This script tests different camera settings for NoIR cameras to optimize
IR illumination performance. It captures images with various configurations
and analyzes brightness, contrast, and image quality metrics.

Usage:
    python3 ethoscope_camera_test.py [--output-dir /path/to/output]

Note: Results are automatically saved in a hostname-specific subfolder to
enable easy comparison across multiple ethoscopes.

Requirements:
    - Raspberry Pi with libcamera
    - NoIR camera (IMX219 or similar)
    - Python 3.7+
    - OpenCV (cv2)
    - NumPy
"""

import argparse
import datetime
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple, Any

try:
    import cv2
    import numpy as np
except ImportError as e:
    print(f"Error: Required Python packages not installed: {e}")
    print("Install with: pip3 install opencv-python numpy")
    sys.exit(1)


class CameraTestConfig:
    """Configuration for camera test settings"""

    def __init__(self, name: str, description: str, **kwargs):
        self.name = name
        self.description = description
        self.settings = kwargs

    def to_libcamera_args(self, width: int = 960, height: int = 720) -> List[str]:
        """Convert settings to libcamera-still command arguments"""
        args = [
            "libcamera-still",
            "--immediate",
            "--width", str(width),
            "--height", str(height),
        ]

        # Add tuning file if specified
        if self.settings.get("tuning_file"):
            args.extend(["--tuning-file", self.settings["tuning_file"]])

        # Add other settings
        for key, value in self.settings.items():
            if key == "tuning_file":
                continue
            elif key == "awbgains":
                args.extend(["--awbgains", f"{value[0]},{value[1]}"])
            else:
                args.extend([f"--{key}", str(value)])

        return args


class ImageAnalyzer:
    """Analyzes captured images for quality metrics"""

    @staticmethod
    def load_image(image_path: str) -> np.ndarray:
        """Load image and convert to grayscale for analysis"""
        img = cv2.imread(image_path)
        if img is None:
            raise ValueError(f"Could not load image: {image_path}")
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    @staticmethod
    def calculate_brightness(image: np.ndarray) -> float:
        """Calculate mean brightness (0-255)"""
        return float(np.mean(image))

    @staticmethod
    def calculate_contrast(image: np.ndarray) -> float:
        """Calculate contrast using standard deviation"""
        return float(np.std(image))

    @staticmethod
    def calculate_dynamic_range(image: np.ndarray) -> Tuple[int, int, int]:
        """Calculate min, max, and range of pixel values"""
        min_val = int(np.min(image))
        max_val = int(np.max(image))
        range_val = max_val - min_val
        return min_val, max_val, range_val

    @staticmethod
    def calculate_histogram_metrics(image: np.ndarray) -> Dict[str, float]:
        """Calculate histogram-based metrics"""
        hist = cv2.calcHist([image], [0], None, [256], [0, 256])
        hist = hist.flatten() / hist.sum()  # Normalize

        # Calculate entropy (measure of information content)
        entropy = -np.sum(hist * np.log2(hist + 1e-10))

        # Calculate histogram spread (weighted standard deviation)
        bins = np.arange(256)
        mean_val = np.sum(bins * hist)
        variance = np.sum(((bins - mean_val) ** 2) * hist)
        hist_spread = np.sqrt(variance)

        return {
            "entropy": float(entropy),
            "histogram_spread": float(hist_spread)
        }

    @classmethod
    def analyze_image(cls, image_path: str) -> Dict[str, Any]:
        """Comprehensive image analysis"""
        try:
            image = cls.load_image(image_path)
            min_val, max_val, range_val = cls.calculate_dynamic_range(image)
            hist_metrics = cls.calculate_histogram_metrics(image)

            file_stats = os.stat(image_path)

            return {
                "file_path": image_path,
                "file_size_bytes": file_stats.st_size,
                "image_shape": image.shape,
                "brightness": cls.calculate_brightness(image),
                "contrast": cls.calculate_contrast(image),
                "min_pixel": min_val,
                "max_pixel": max_val,
                "dynamic_range": range_val,
                "entropy": hist_metrics["entropy"],
                "histogram_spread": hist_metrics["histogram_spread"],
                "analysis_timestamp": datetime.datetime.now().isoformat()
            }
        except Exception as e:
            return {
                "file_path": image_path,
                "error": str(e),
                "analysis_timestamp": datetime.datetime.now().isoformat()
            }


class EthoscopeCameraTester:
    """Main camera testing class"""

    def __init__(self, output_dir: str = "/tmp/ethoscope_camera_test"):
        # Get hostname and create hostname-specific subdirectory
        hostname = socket.gethostname()
        self.output_dir = Path(output_dir) / hostname
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.results = []

        # Define test configurations
        self.test_configs = [
            CameraTestConfig(
                "baseline_default",
                "Default camera settings (no optimizations)",
            ),
            CameraTestConfig(
                "baseline_noir",
                "NoIR tuning file only",
                tuning_file="/usr/share/libcamera/ipa/rpi/vc4/imx219_noir.json"
            ),
            CameraTestConfig(
                "noir_gain4",
                "NoIR + moderate gain (4) + manual white balance",
                tuning_file="/usr/share/libcamera/ipa/rpi/vc4/imx219_noir.json",
                gain=4,
                awbgains=[1.0, 1.0]
            ),
            CameraTestConfig(
                "noir_gain6_balanced",
                "NoIR + balanced gain (6) + 50ms exposure + brightness boost",
                tuning_file="/usr/share/libcamera/ipa/rpi/vc4/imx219_noir.json",
                gain=6,
                shutter=50000,
                awbgains=[1.0, 1.0],
                brightness=0.1
            ),
            CameraTestConfig(
                "noir_gain8_max",
                "NoIR + high gain (8) for maximum IR sensitivity",
                tuning_file="/usr/share/libcamera/ipa/rpi/vc4/imx219_noir.json",
                gain=8,
                awbgains=[1.0, 1.0]
            ),
            CameraTestConfig(
                "noir_long_exposure",
                "NoIR + gain 4 + long exposure (100ms) for low light",
                tuning_file="/usr/share/libcamera/ipa/rpi/vc4/imx219_noir.json",
                gain=4,
                shutter=100000,
                awbgains=[1.0, 1.0]
            ),
        ]

    def check_camera_availability(self) -> bool:
        """Check if camera is available and get info"""
        try:
            result = subprocess.run(
                ["libcamera-hello", "--list-cameras"],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode == 0:
                print("Camera detection:")
                print(result.stdout)
                return True
            else:
                print(f"Camera detection failed: {result.stderr}")
                return False

        except Exception as e:
            print(f"Error checking camera: {e}")
            return False

    def check_noir_tuning_file(self) -> bool:
        """Check if NoIR tuning file exists"""
        tuning_file = "/usr/share/libcamera/ipa/rpi/vc4/imx219_noir.json"
        exists = os.path.exists(tuning_file)
        print(f"NoIR tuning file {'found' if exists else 'NOT FOUND'}: {tuning_file}")
        return exists

    def _parse_libcamera_output(self, output_text: str) -> Dict[str, Any]:
        """Parse libcamera output to extract actual camera settings used"""
        settings = {}

        try:
            # Split into lines and look for camera parameter information
            lines = output_text.split('\n')

            for line in lines:
                line = line.strip()

                # Look for exposure time (various possible formats)
                if 'exposure' in line.lower() and ('time' in line.lower() or 'us' in line or 'ms' in line):
                    # Try to extract numeric value
                    import re
                    # Look for patterns like "exposure: 12345us" or "ExposureTime: 12345"
                    match = re.search(r'(?:exposure.*?time|exposuretime).*?(\d+(?:\.\d+)?)\s*(?:us|μs|ms)?', line.lower())
                    if match:
                        exposure_val = float(match.group(1))
                        # Convert to microseconds if needed
                        if 'ms' in line.lower():
                            exposure_val *= 1000
                        settings['exposure_time_us'] = exposure_val

                # Look for analogue gain
                if 'gain' in line.lower() and ('analogue' in line.lower() or 'analog' in line.lower()):
                    import re
                    match = re.search(r'(?:analogue.*?gain|analoggain).*?(\d+(?:\.\d+)?)', line.lower())
                    if match:
                        settings['analogue_gain'] = float(match.group(1))

                # Look for digital gain
                if 'gain' in line.lower() and 'digital' in line.lower():
                    import re
                    match = re.search(r'digital.*?gain.*?(\d+(?:\.\d+)?)', line.lower())
                    if match:
                        settings['digital_gain'] = float(match.group(1))

                # Look for AWB gains
                if 'awb' in line.lower() and 'gain' in line.lower():
                    import re
                    # Look for patterns like "AwbGains: [1.23, 4.56]" or "awb gains: 1.23, 4.56"
                    match = re.search(r'awb.*?gain.*?\[?(\d+(?:\.\d+)?)[,\s]+(\d+(?:\.\d+)?)', line.lower())
                    if match:
                        settings['awb_gains'] = [float(match.group(1)), float(match.group(2))]

                # Look for frame rate
                if 'framerate' in line.lower() or 'fps' in line.lower():
                    import re
                    match = re.search(r'(?:framerate|fps).*?(\d+(?:\.\d+)?)', line.lower())
                    if match:
                        settings['framerate'] = float(match.group(1))

                # Look for colour temperature
                if 'colour' in line.lower() and 'temperature' in line.lower():
                    import re
                    match = re.search(r'colour.*?temperature.*?(\d+)', line.lower())
                    if match:
                        settings['colour_temperature'] = int(match.group(1))

        except Exception as e:
            settings['parse_error'] = str(e)

        return settings

    def capture_image(self, config: CameraTestConfig, width: int = 960, height: int = 720) -> Tuple[bool, str, Dict]:
        """Capture image with specific configuration and return actual camera settings"""
        output_path = self.output_dir / f"{config.name}.jpg"

        cmd = config.to_libcamera_args(width, height)
        cmd.extend(["--output", str(output_path)])

        print(f"Capturing {config.name}...")
        print(f"Command: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )

            # Parse the libcamera output for actual settings used
            actual_settings = self._parse_libcamera_output(result.stderr + result.stdout)

            if result.returncode == 0 and output_path.exists():
                print(f"✓ Successfully captured: {output_path}")
                if actual_settings:
                    print(f"  Actual settings: {actual_settings}")
                return True, str(output_path), actual_settings
            else:
                error_msg = f"Capture failed: {result.stderr}"
                print(f"✗ {error_msg}")
                return False, error_msg, {}

        except subprocess.TimeoutExpired:
            error_msg = "Capture timed out (30s)"
            print(f"✗ {error_msg}")
            return False, error_msg, {}
        except Exception as e:
            error_msg = f"Capture error: {e}"
            print(f"✗ {error_msg}")
            return False, error_msg, {}

    def run_test_suite(self, width: int = 960, height: int = 720) -> bool:
        """Run complete test suite"""
        print("=" * 60)
        print("ETHOSCOPE CAMERA IR OPTIMIZATION TEST")
        print("=" * 60)
        print(f"Output directory: {self.output_dir}")
        print(f"Test resolution: {width}x{height}")
        print(f"Test time: {datetime.datetime.now()}")
        print()

        # Pre-flight checks
        if not self.check_camera_availability():
            print("ERROR: Camera not available. Aborting.")
            return False

        self.check_noir_tuning_file()
        print()

        # Capture images with different configurations
        successful_captures = 0
        for config in self.test_configs:
            print(f"Testing: {config.description}")
            success, path_or_error, actual_settings = self.capture_image(config, width, height)

            if success:
                # Analyze the captured image
                analysis = ImageAnalyzer.analyze_image(path_or_error)
                analysis["config_name"] = config.name
                analysis["config_description"] = config.description
                analysis["config_settings"] = config.settings
                analysis["actual_camera_settings"] = actual_settings  # Add parsed libcamera settings
                self.results.append(analysis)
                successful_captures += 1
            else:
                # Record failed capture
                self.results.append({
                    "config_name": config.name,
                    "config_description": config.description,
                    "config_settings": config.settings,
                    "actual_camera_settings": actual_settings,
                    "error": path_or_error,
                    "analysis_timestamp": datetime.datetime.now().isoformat()
                })

            print()
            time.sleep(1)  # Brief pause between captures

        print(f"Captured {successful_captures}/{len(self.test_configs)} images successfully")
        return successful_captures > 0

    def generate_report(self) -> str:
        """Generate analysis report"""
        report_path = self.output_dir / "analysis_report.json"

        # Sort results by brightness for ranking
        successful_results = [r for r in self.results if "error" not in r]
        successful_results.sort(key=lambda x: x.get("brightness", 0), reverse=True)

        # Generate summary
        summary = {
            "test_metadata": {
                "test_time": datetime.datetime.now().isoformat(),
                "total_tests": len(self.test_configs),
                "successful_tests": len(successful_results),
                "output_directory": str(self.output_dir)
            },
            "results": self.results,
            "ranking_by_brightness": [
                {
                    "rank": i + 1,
                    "config_name": result["config_name"],
                    "brightness": result["brightness"],
                    "contrast": result["contrast"],
                    "dynamic_range": result["dynamic_range"],
                    "file_size_bytes": result["file_size_bytes"],
                    "actual_exposure_time_us": result.get("actual_camera_settings", {}).get("exposure_time_us", "N/A"),
                    "actual_analogue_gain": result.get("actual_camera_settings", {}).get("analogue_gain", "N/A")
                }
                for i, result in enumerate(successful_results)
            ],
            "recommendations": self._generate_recommendations(successful_results)
        }

        # Save detailed JSON report
        with open(report_path, "w") as f:
            json.dump(summary, f, indent=2)

        # Generate human-readable summary
        return self._format_summary_report(summary)

    def _generate_recommendations(self, results: List[Dict]) -> Dict[str, Any]:
        """Generate recommendations based on analysis"""
        if not results:
            return {"error": "No successful captures to analyze"}

        # Find baseline and best performing configurations
        baseline = next((r for r in results if r["config_name"] == "baseline_default"), None)
        best_brightness = results[0] if results else None
        best_contrast = max(results, key=lambda x: x["contrast"])
        best_dynamic_range = max(results, key=lambda x: x["dynamic_range"])

        recommendations = {
            "best_overall_brightness": {
                "config": best_brightness["config_name"],
                "brightness": best_brightness["brightness"],
                "improvement_vs_baseline": None
            },
            "best_contrast": {
                "config": best_contrast["config_name"],
                "contrast": best_contrast["contrast"]
            },
            "best_dynamic_range": {
                "config": best_dynamic_range["config_name"],
                "dynamic_range": best_dynamic_range["dynamic_range"]
            }
        }

        if baseline and best_brightness:
            improvement = ((best_brightness["brightness"] - baseline["brightness"]) / baseline["brightness"]) * 100
            recommendations["best_overall_brightness"]["improvement_vs_baseline"] = f"{improvement:.1f}%"

        # Recommend balanced configuration
        balanced_configs = [r for r in results if "balanced" in r["config_name"]]
        if balanced_configs:
            recommendations["recommended_for_tracking"] = {
                "config": balanced_configs[0]["config_name"],
                "reason": "Good balance of brightness, contrast, and performance for real-time tracking"
            }

        return recommendations

    def _format_summary_report(self, summary: Dict) -> str:
        """Format human-readable summary report"""
        lines = []
        lines.append("=" * 80)
        lines.append("ETHOSCOPE CAMERA TEST RESULTS SUMMARY")
        lines.append("=" * 80)
        lines.append(f"Test completed: {summary['test_metadata']['test_time']}")
        lines.append(f"Successful tests: {summary['test_metadata']['successful_tests']}/{summary['test_metadata']['total_tests']}")
        lines.append("")

        # Brightness ranking
        lines.append("BRIGHTNESS RANKING (Higher is Better for IR):")
        lines.append("-" * 80)
        lines.append(f"{'Rank':<4} {'Config':<20} {'Brightness':<10} {'Contrast':<8} {'Range':<6} {'ExposureTime':<12} {'Gain':<6}")
        lines.append("-" * 80)
        for rank_info in summary["ranking_by_brightness"]:
            exposure = rank_info.get('actual_exposure_time_us', 'N/A')
            if exposure != 'N/A' and isinstance(exposure, (int, float)):
                exposure_str = f"{exposure:.0f}μs"
            else:
                exposure_str = str(exposure)

            gain = rank_info.get('actual_analogue_gain', 'N/A')
            if gain != 'N/A' and isinstance(gain, (int, float)):
                gain_str = f"{gain:.1f}x"
            else:
                gain_str = str(gain)

            lines.append(
                f"{rank_info['rank']:2d}.  {rank_info['config_name']:<20} "
                f"{rank_info['brightness']:6.1f}    "
                f"{rank_info['contrast']:6.1f}  "
                f"{rank_info['dynamic_range']:3d}    "
                f"{exposure_str:<12} "
                f"{gain_str:<6}"
            )

        lines.append("")

        # Recommendations
        if "recommendations" in summary:
            rec = summary["recommendations"]
            lines.append("RECOMMENDATIONS:")
            lines.append("-" * 20)

            if "best_overall_brightness" in rec:
                best = rec["best_overall_brightness"]
                lines.append(f"Best brightness: {best['config']} ({best['brightness']:.1f})")
                if best.get("improvement_vs_baseline"):
                    lines.append(f"  Improvement vs baseline: {best['improvement_vs_baseline']}")

            if "recommended_for_tracking" in rec:
                track_rec = rec["recommended_for_tracking"]
                lines.append(f"Recommended for tracking: {track_rec['config']}")
                lines.append(f"  Reason: {track_rec['reason']}")

        lines.append("")
        lines.append(f"Detailed results saved to: {summary['test_metadata']['output_directory']}/analysis_report.json")
        lines.append(f"Test images saved to: {summary['test_metadata']['output_directory']}/")
        lines.append("")

        return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Test Ethoscope camera settings for IR optimization"
    )
    parser.add_argument(
        "--output-dir",
        default="/tmp/ethoscope_camera_test",
        help="Output directory for test images and results (hostname subfolder will be created automatically)"
    )
    parser.add_argument(
        "--width",
        type=int,
        default=960,
        help="Image width (default: 960)"
    )
    parser.add_argument(
        "--height",
        type=int,
        default=720,
        help="Image height (default: 720)"
    )

    args = parser.parse_args()

    # Run the test suite
    tester = EthoscopeCameraTester(args.output_dir)

    if tester.run_test_suite(args.width, args.height):
        # Generate and display report
        summary_report = tester.generate_report()
        print(summary_report)
        return 0
    else:
        print("Test suite failed - no images captured successfully")
        return 1


if __name__ == "__main__":
    sys.exit(main())