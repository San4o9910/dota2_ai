CREATE UNIQUE INDEX `orders_one_unresolved_coach_per_user` ON `orders` (`user_id`) WHERE
        product_code = 'coach_30_days'
        AND (
          status IN ('created', 'pending', 'waiting_for_capture')
          OR (
            status = 'succeeded'
            AND (credited_at IS NULL OR fulfillment_status <> 'granted')
          )
        )
      ;--> statement-breakpoint
DROP INDEX `orders_one_open_coach_per_user`;
