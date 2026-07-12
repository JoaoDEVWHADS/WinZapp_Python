import logging
import numpy as np

def apply_noise_gate(audio_bytes: bytes, rate: int, channels: int, threshold_db: float = -40.0, attenuation: float = 0.1) -> bytes:
    """
    Applies a simple, soft-knee noise gate filter to raw 16-bit PCM audio bytes.
    This attenuates silent or low-volume background noise (computer fans, room hum)
    when the user is not actively speaking, without distorting the voice.
    """
    try:
        # Load raw bytes as 16-bit signed PCM samples
        samples = np.frombuffer(audio_bytes, dtype=np.int16).copy()
        
        # 20ms block size
        block_size = int(rate * 0.02) * channels
        if block_size <= 0:
            return audio_bytes
            
        num_samples = len(samples)
        
        # Compute RMS for all blocks first to estimate noise floor
        rms_values = []
        for i in range(0, num_samples, block_size):
            block = samples[i:i+block_size]
            if len(block) == 0:
                continue
            rms = np.sqrt(np.mean(block.astype(np.float32) ** 2))
            rms_values.append(rms)

        if not rms_values:
            return audio_bytes

        # Use the 15th percentile of RMS to find the background noise floor (pauses)
        noise_floor = float(np.percentile(rms_values, 15))
        
        # Threshold is 2.5x the noise floor, bounded between -45dB (180) and -22dB (2600)
        threshold = max(180.0, min(2600.0, noise_floor * 2.5))
        
        logging.info("[audio_processing] Dynamic noise gate: estimated noise floor RMS = %.2f, threshold set to %.2f", noise_floor, threshold)
        
        # Envelope parameters for gain smoothing (faster attack/release response)
        gain = 1.0
        attack = 0.35
        release = 0.15
        
        for i in range(0, num_samples, block_size):
            block = samples[i:i+block_size]
            if len(block) == 0:
                continue
            
            rms = rms_values[i // block_size] if (i // block_size) < len(rms_values) else np.sqrt(np.mean(block.astype(np.float32) ** 2))
            
            # Determine target gain factor
            target_gain = 1.0 if rms >= threshold else attenuation
            
            # Smooth the gain transition
            if target_gain > gain:
                gain = gain + attack * (target_gain - gain)
            else:
                gain = gain + release * (target_gain - gain)
                
            # Apply smoothed gain to the block
            samples[i:i+block_size] = (block.astype(np.float32) * gain).astype(np.int16)
            
        return samples.tobytes()
    except Exception as e:
        logging.error("[audio_processing] Error applying noise gate: %s", e)
        return audio_bytes
