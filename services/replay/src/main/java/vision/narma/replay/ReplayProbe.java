package vision.narma.replay;

import com.google.gson.Gson;
import java.io.BufferedWriter;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.security.MessageDigest;
import java.util.*;
import skadistats.clarity.Clarity;
import skadistats.clarity.model.CombatLogEntry;
import skadistats.clarity.model.Entity;
import skadistats.clarity.model.FieldPath;
import skadistats.clarity.model.StringTable;
import skadistats.clarity.processor.entities.*;
import skadistats.clarity.processor.gameevents.OnCombatLogEntry;
import skadistats.clarity.processor.reader.OnTickEnd;
import skadistats.clarity.processor.reader.OnMessage;
import skadistats.clarity.processor.runner.Context;
import skadistats.clarity.processor.runner.SimpleRunner;
import skadistats.clarity.processor.stringtables.UsesStringTable;
import skadistats.clarity.processor.stringtables.OnStringTableCreated;
import skadistats.clarity.source.MappedFileSource;
import skadistats.clarity.wire.shared.common.proto.CommonNetworkBaseTypes.CNETMsg_Tick;

/** Independent research probe. Emits source observations, never a coaching verdict. */
@UsesEntities
@UsesStringTable("EntityNames")
public final class ReplayProbe {
    private static final Gson JSON = new Gson();
    private static final long MAX_OUTPUT_BYTES = 50L * 1024 * 1024;
    private static final long MAX_INPUT_BYTES = 512L * 1024 * 1024;
    private final BufferedWriter writer;
    private final long started = System.nanoTime();
    private final Map<Integer, Map<String, Object>> previous = new HashMap<>();
    private final Map<String, Long> counts = new TreeMap<>();
    private final Set<String> described = new HashSet<>();
    private final Set<String> relevantClasses = new TreeSet<>();
    private final Map<String, StringTable> nameTables = new TreeMap<>();
    private long bytes, events, ticks, realTicks;
    private int finalTick;
    private Integer serverTick;
    private Entity rules;
    private Double gameStart;

    private ReplayProbe(BufferedWriter writer) { this.writer = writer; }

    private static Map<String, Object> map(Object... values) {
        Map<String, Object> result = new LinkedHashMap<>();
        for (int i = 0; i < values.length; i += 2) result.put((String) values[i], values[i + 1]);
        return result;
    }
    private void emit(Map<String, Object> record) throws IOException {
        record.put("eventId", ++events);
        String line = JSON.toJson(record) + "\n";
        bytes += line.getBytes(StandardCharsets.UTF_8).length;
        if (bytes > MAX_OUTPUT_BYTES) throw new IOException("OUTPUT_LIMIT");
        writer.write(line);
    }
    private static Object property(Entity entity, String key) {
        return entity != null && entity.hasProperty(key) ? entity.getProperty(key) : null;
    }
    private static Object first(Entity entity, String... keys) {
        for (String key : keys) { Object value = property(entity, key); if (value != null) return value; }
        return null;
    }
    private static Double number(Object value) { return value instanceof Number n ? n.doubleValue() : null; }
    private Map<String, Object> clock(Context ctx) {
        Double raw = number(first(rules, "m_pGameRules.m_fGameTime", "m_pGameRules.m_flGameTime"));
        Object paused = first(rules, "m_pGameRules.m_bGamePaused", "m_pGameRules.m_bIsPaused");
        Double pausedTicks = number(property(rules, "m_pGameRules.m_nTotalPausedTicks"));
        Double pauseStartTick = number(property(rules, "m_pGameRules.m_nPauseStartTick"));
        Double derived = serverTick != null && pausedTicks != null
            ? ((Boolean.TRUE.equals(paused) && pauseStartTick != null ? pauseStartTick : serverTick.doubleValue()) - pausedTicks) * ctx.getMillisPerTick() / 1000.0 : null;
        Double start = number(first(rules, "m_pGameRules.m_flGameStartTime", "m_pGameRules.m_fGameStartTime"));
        if (start != null && start > 0) gameStart = start;
        return map("tick", ctx.getTick(), "serverTick", serverTick, "millisPerTick", ctx.getMillisPerTick(),
            "totalPausedTicks", pausedTicks, "pauseStartTick", pauseStartTick, "gameTimeRaw", raw,
            "gameTimeDerivedFromServerTicks", derived, "gameStartTimeRaw", gameStart,
            "matchTimeEstimate", derived != null && gameStart != null ? derived - gameStart : null,
            "matchTime", raw != null && gameStart != null ? raw - gameStart : null,
            "paused", paused);
    }
    private static String kind(Entity entity) {
        String name = entity.getDtClass().getDtName().toLowerCase(Locale.ROOT);
        if (name.equals("cdota_npc_observer_ward") || name.equals("cdota_npc_observer_ward_truesight")) return "ward";
        if (name.equals("cdota_basenpc_tower")) return "tower";
        return null;
    }
    private Map<String, Object> snapshot(Context ctx, Entity entity) {
        Object nameIndex = first(entity, "m_iUnitNameIndex", "m_iNameIndex");
        String entityName = null;
        Object entityNameIndex = property(entity, "m_pEntity.m_nameStringTableIndex");
        var table = nameTables.get("EntityNames");
        if (entityNameIndex instanceof Number index && table != null && table.hasIndex(index.intValue())) {
            entityName = table.getNameByIndex(index.intValue());
        }
        return map("entityHandle", Integer.toUnsignedLong(entity.getHandle()), "entityIndex", entity.getIndex(),
            "entitySerial", entity.getSerial(), "class", entity.getDtClass().getDtName(), "kind", kind(entity),
            "entityName", entityName, "unitNameIndex", nameIndex, "entityNameIndex", entityNameIndex,
            "team", property(entity, "m_iTeamNum"), "health", property(entity, "m_iHealth"),
            "maxHealth", property(entity, "m_iMaxHealth"), "lifeState", property(entity, "m_lifeState"),
            "cellX", first(entity, "CBodyComponent.m_cellX", "m_cellX"), "cellY", first(entity, "CBodyComponent.m_cellY", "m_cellY"),
            "cellZ", first(entity, "CBodyComponent.m_cellZ", "m_cellZ"),
            "offsetX", first(entity, "CBodyComponent.m_vecX", "m_vecX"), "offsetY", first(entity, "CBodyComponent.m_vecY", "m_vecY"),
            "offsetZ", first(entity, "CBodyComponent.m_vecZ", "m_vecZ"),
            "ownerHandle", first(entity, "m_hOwnerEntity"), "createdTimeRaw", property(entity, "m_flCreateTime"),
            "playerOwnerIdRaw", first(entity, "m_nPlayerOwnerID"));
    }
    private void describe(Context ctx, Entity entity) throws IOException {
        String name = entity.getDtClass().getDtName();
        if (!described.add(name)) return;
        List<String> fields = new ArrayList<>();
        var iterator = entity.getState().fieldPathIterator();
        while (iterator.hasNext()) {
            String field = entity.getDtClass().getNameForFieldPath(iterator.next());
            if (field.matches("(?i).*(time|pause|health|life|name|teamnum|cell|vision|fog|owner|playerid|m_vec[XYZ]).*") && !field.matches(".*\\.[0-9]{4}.*") && fields.size() < 500) fields.add(field);
        }
        Map<String, Object> record = clock(ctx);
        record.putAll(map("type", "schema", "class", name, "fields", fields));
        emit(record);
    }
    private void observation(Context ctx, Entity entity, String type) throws IOException {
        String kind = kind(entity);
        if (kind == null) return;
        describe(ctx, entity);
        Map<String, Object> state = snapshot(ctx, entity);
        if (type.equals("state") && state.equals(previous.get(entity.getHandle()))) return;
        previous.put(entity.getHandle(), state);
        counts.merge(kind + "_" + type, 1L, Long::sum);
        Map<String, Object> record = clock(ctx);
        record.putAll(state);
        record.put("type", type);
        emit(record);
    }
    @OnEntityCreated
    public void created(Context ctx, Entity entity) throws IOException {
        if (entity.getDtClass().getDtName().toLowerCase(Locale.ROOT).matches(".*(ward|tower|rules|world|team).*")) relevantClasses.add(entity.getDtClass().getDtName());
        if (entity.getDtClass().getDtName().equals("CDOTAGamerulesProxy")) { rules = entity; describe(ctx, entity); }
        observation(ctx, entity, "created");
    }
    @OnEntityUpdated
    public void updated(Context ctx, Entity entity, FieldPath[] paths, int count) throws IOException {
        observation(ctx, entity, "state");
    }
    @OnEntityDeleted
    public void deleted(Context ctx, Entity entity) throws IOException {
        observation(ctx, entity, "deleted");
        previous.remove(entity.getHandle());
        if (rules == entity) rules = null;
    }
    @OnEntityLeft
    public void left(Context ctx, Entity entity) throws IOException {
        // Network/PVS scope loss is deliberately a separate event, never death/removal.
        observation(ctx, entity, "scope_left");
    }
    @OnEntityEntered
    public void entered(Context ctx, Entity entity) throws IOException { observation(ctx, entity, "scope_entered"); }
    @OnTickEnd
    public void tick(Context ctx, boolean synthetic) throws IOException {
        ticks++; if (!synthetic) realTicks++; finalTick = ctx.getTick();
        if (System.nanoTime() - started > 295_000_000_000L) throw new IOException("WALL_TIME_LIMIT");
        if (!synthetic && ctx.getTick() % 300 == 0) {
            Map<String, Object> record = clock(ctx); record.put("type", "clock_anchor"); emit(record);
        }
    }
    @OnMessage(CNETMsg_Tick.class)
    public void serverTick(CNETMsg_Tick message) { serverTick = message.getTick(); }
    @OnStringTableCreated
    public void table(int index, StringTable table) { nameTables.put(table.getName(), table); }
    @OnCombatLogEntry
    public void combat(Context ctx, CombatLogEntry entry) throws IOException {
        String target = entry.hasTargetName() ? entry.getTargetName() : "";
        if (!entry.getType().name().equals("DOTA_COMBATLOG_DEATH") || !(target.contains("tower") || target.contains("ward"))) return;
        Map<String, Object> record = clock(ctx);
        record.putAll(map("type", "combat_death", "target", target,
            "combatTimestamp", entry.hasTimestamp() ? entry.getTimestamp() : null,
            "targetTeam", entry.hasTargetTeam() ? entry.getTargetTeam() : null));
        counts.merge("combat_death", 1L, Long::sum); emit(record);
    }
    private static String hash(Path path) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (var input = Files.newInputStream(path)) { byte[] buffer = new byte[1024 * 1024]; int n;
            while ((n = input.read(buffer)) >= 0) digest.update(buffer, 0, n); }
        return HexFormat.of().formatHex(digest.digest());
    }
    public static void main(String[] args) throws Exception {
        if (args.length != 2) throw new IllegalArgumentException("Usage: ReplayProbe replay.dem new-events.jsonl");
        Path input = Path.of(args[0]).toRealPath(), output = Path.of(args[1]);
        if (!Files.isRegularFile(input) || Files.size(input) > MAX_INPUT_BYTES) throw new IllegalArgumentException("INVALID_INPUT_SIZE");
        Map<String, Object> summary = map("parser", "com.skadistats:clarity:4.0.1", "sha256", hash(input), "inputBytes", Files.size(input));
        try (var source = new MappedFileSource(input.toString())) {
            var header = Clarity.headerForSource(source);
            summary.putAll(map("game", header.getGame(), "map", header.getMapName(), "build", header.getBuildNum(), "networkProtocol", header.getNetworkProtocol()));
        }
        try (var source = new MappedFileSource(input.toString())) {
            var info = Clarity.infoForSource(source);
            if (!info.hasGameInfo() || !info.getGameInfo().hasDota() || !info.getGameInfo().getDota().hasMatchId()
                || info.getGameInfo().getDota().getMatchId() <= 0 || info.getPlaybackTicks() <= 0) throw new IOException("INVALID_EPILOGUE");
            summary.putAll(map("matchId", Long.toUnsignedString(info.getGameInfo().getDota().getMatchId()),
                "metadataPlayers", info.getGameInfo().getDota().getPlayerInfoCount(), "playbackTicks", info.getPlaybackTicks(), "playbackSeconds", info.getPlaybackTime()));
        }
        try (var writer = Files.newBufferedWriter(output, StandardCharsets.UTF_8, StandardOpenOption.CREATE_NEW);
             var source = new MappedFileSource(input.toString())) {
            ReplayProbe probe = new ReplayProbe(writer);
            probe.emit(map("type", "source", "metadata", summary));
            new SimpleRunner(source).runWith(probe);
            if (probe.finalTick != ((Number) summary.get("playbackTicks")).intValue()) throw new IOException("FINAL_TICK_MISMATCH");
            summary.putAll(map("complete", true, "ticksVisited", probe.ticks, "nonSyntheticTicks", probe.realTicks,
                "lastTick", probe.finalTick, "gameStartTimeRaw", probe.gameStart, "eventCounts", probe.counts,
                "relevantClasses", probe.relevantClasses, "stringTables", probe.nameTables.keySet(), "wallSeconds", (System.nanoTime() - probe.started) / 1e9));
            probe.emit(map("type", "summary", "summary", summary));
            System.out.println(JSON.toJson(summary));
        }
    }
}
