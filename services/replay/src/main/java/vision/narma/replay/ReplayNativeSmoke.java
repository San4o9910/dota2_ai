package vision.narma.replay;

import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import org.xerial.snappy.Snappy;

/** Exercises native decompression with synthetic bytes; no replay or provider call. */
public final class ReplayNativeSmoke {
    private ReplayNativeSmoke() { }
    public static void main(String[] args) throws Exception {
        byte[] source = "NARMA replay packet decompression smoke check".getBytes(StandardCharsets.UTF_8);
        byte[] packed = Snappy.compress(source);
        if (!Arrays.equals(source, Snappy.uncompress(packed))) {
            throw new IllegalStateException("REPLAY_NATIVE_ROUNDTRIP_FAILED");
        }
        System.out.println("REPLAY_NATIVE_OK");
    }
}
