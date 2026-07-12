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
        
        # Calculate amplitude threshold from decibel value (16-bit limit: 32768)
        # db = 20 * log10(amplitude / 32768) -> amplitude = 32768 * 10^(db / 20)
        threshold = 32768.0 * (10.0 ** (threshold_db / 20.0))
        
        # Envelope parameters for gain smoothing
        # attack determines how quickly the gate opens when speech is detected.
        # release determines how quickly the gate closes when speech stops.
        gain = 1.0
        attack = 0.25
        release = 0.05
        
        for i in range(0, num_samples, block_size):
            block = samples[i:i+block_size]
            if len(block) == 0:
                continue
            
            # Compute Root Mean Square (RMS) amplitude of block
            rms = np.sqrt(np.mean(block.astype(np.float32) ** 2))
            
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
