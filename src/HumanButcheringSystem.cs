using System;
using System.Reflection;
using HarmonyLib;
using Newtonsoft.Json;
using Vintagestory.API.Common;
using Vintagestory.API.Common.Entities;
using Vintagestory.API.Datastructures;
using Vintagestory.API.MathTools;
using Vintagestory.API.Server;
using Vintagestory.GameContent;

namespace OutlawsHumanButchering;

/// <summary>
/// Guarantees exactly one outlaw head per body, whichever way it is butchered.
/// Butchering multiplies every harvest drop (x0.5 in the field, x0.8..1.2 on the table),
/// so the head is removed from the regular drops and handed out here instead:
///  - field harvesting: through IHarvestableDrops, which the game does not multiply;
///  - butcher table: a prefix on Butchering's table processing, read from the
///    carcass item attribute "guaranteedHead".
/// </summary>
public class HumanButcheringSystem : ModSystem
{
    public const string ModId = "outlawshumanbutchering";
    public const string HeadBehaviorCode = ModId + ".guaranteedhead";
    private const string TableType = "Butchering.src.common.blockentity.BlockEntityButcherTable";
    private const string HookType = "Butchering.src.common.blockentity.BlockEntityButcherHook";

    private Harmony harmony;
    private static ILogger log;

    public override void Start(ICoreAPI api)
    {
        api.RegisterEntityBehaviorClass(HeadBehaviorCode, typeof(EntityBehaviorGuaranteedHead));
    }

    public override void StartServerSide(ICoreServerAPI sapi)
    {
        log = sapi.Logger;
        harmony = new Harmony(ModId);
        MethodInfo table = AccessTools.TypeByName(TableType) is Type t ? AccessTools.Method(t, "processItem") : null;
        MethodInfo hook = AccessTools.TypeByName(HookType) is Type h ? AccessTools.Method(h, "processItem") : null;
        if (table == null || hook == null)
        {
            sapi.Logger.Error($"[{ModId}] Butchering's hook/table code was not found (hook: {hook != null}, table: {table != null}). Was Butchering updated?");
        }
        if (hook != null)
        {
            harmony.Patch(hook, prefix: new HarmonyMethod(typeof(HumanButcheringSystem).GetMethod(nameof(HookPrefix), BindingFlags.Static | BindingFlags.Public)));
        }
        if (table != null)
        {
            harmony.Patch(table, prefix: new HarmonyMethod(typeof(HumanButcheringSystem).GetMethod(nameof(TablePrefix), BindingFlags.Static | BindingFlags.Public)));
        }
        sapi.Logger.Notification($"[{ModId}] Patched the butcher hook and table.");
    }

    /// <summary>
    /// Bodies taken from the creative inventory never had an entity, so Butchering has no
    /// "AnimalDrops" for them and gives no meat, fat or hide. Fill in the default drops.
    /// </summary>
    private static void EnsureAnimalDrops(ItemStack carcass)
    {
        if (carcass == null) return;
        // the bone pile Butchering leaves after the table (a real body gets it from Outlaws' deaddecay)
        if (!carcass.Attributes.HasAttribute("AnimalCarcass"))
        {
            string bones = carcass.ItemAttributes?["fallbackAnimalCarcass"].AsString(null);
            if (bones != null) carcass.Attributes.SetString("AnimalCarcass", bones);
        }
        if (carcass.Attributes.HasAttribute("AnimalDrops")) return;
        JsonObject fallback = carcass.ItemAttributes?["fallbackAnimalDrops"];
        if (fallback == null || !fallback.Exists) return;
        BlockDropItemStack[] drops = fallback.AsObject<BlockDropItemStack[]>(null, HumanButcheringSystem.ModId);
        if (drops == null) return;
        carcass.Attributes.SetString("AnimalDrops", JsonConvert.SerializeObject(drops));
    }

    public static void HookPrefix(BlockEntity __instance)
    {
        try
        {
            if (__instance.Api?.Side != EnumAppSide.Server) return;
            EnsureAnimalDrops((__instance as IBlockEntityContainer)?.Inventory?[0]?.Itemstack);
        }
        catch (Exception e)
        {
            log?.Error($"[{ModId}] Failed to prepare the body on the hook: {e}");
        }
    }

    public override void Dispose()
    {
        harmony?.UnpatchAll(ModId);
    }

    public static void TablePrefix(BlockEntity __instance)
    {
        try
        {
            if (__instance.Api?.Side != EnumAppSide.Server) return;
            ItemStack carcass = (__instance as IBlockEntityContainer)?.Inventory?[0]?.Itemstack;
            EnsureAnimalDrops(carcass); // humans and hounds
            string code = carcass?.ItemAttributes?["guaranteedHead"].AsString(null);
            if (code == null) return;
            Item head = __instance.Api.World.GetItem(new AssetLocation(code));
            if (head == null)
            {
                log?.Warning($"[{ModId}] Head item '{code}' does not exist.");
                return;
            }
            __instance.Api.World.SpawnItemEntity(new ItemStack(head), __instance.Pos.ToVec3d().Add(0.5, 1.1, 0.5));
        }
        catch (Exception e)
        {
            log?.Error($"[{ModId}] Failed to drop the head at the butcher table: {e}");
        }
    }
}

/// <summary>Adds exactly one head to the field-harvest drops of an outlaw.</summary>
public class EntityBehaviorGuaranteedHead : EntityBehavior, IHarvestableDrops
{
    private AssetLocation head;

    public EntityBehaviorGuaranteedHead(Entity entity) : base(entity) { }

    public override void Initialize(EntityProperties properties, JsonObject attributes)
    {
        base.Initialize(properties, attributes);
        string code = attributes["head"].AsString(null);
        if (code != null) head = new AssetLocation(code);
    }

    public ItemStack[] GetHarvestableDrops(IWorldAccessor world, BlockPos pos, IPlayer byPlayer)
    {
        Item item = head == null ? null : world.GetItem(head);
        return item == null ? null : new[] { new ItemStack(item) };
    }

    public override string PropertyName() => HumanButcheringSystem.HeadBehaviorCode;
}
