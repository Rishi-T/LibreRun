// LibreRun compliant: multiple test modes via +test=<name> plusarg

`timescale 1ns/1ps

module tb_counter;

    // -------------------------------------------------------------------------
    // Parameters
    // -------------------------------------------------------------------------
    localparam int WIDTH     = 4;
    localparam int CLK_HALF  = 5;   // 10ns clock period

    // -------------------------------------------------------------------------
    // DUT signals
    // -------------------------------------------------------------------------
    logic             clk;
    logic             rst_n;
    logic             en;
    logic             dir;
    logic             load_en;
    logic [WIDTH-1:0] load_val;
    logic [WIDTH-1:0] count;
    logic             overflow;

    // -------------------------------------------------------------------------
    // Test tracking
    // -------------------------------------------------------------------------
    string test_name;
    int    seed;
    int    errors;

    // -------------------------------------------------------------------------
    // DUT instantiation
    // -------------------------------------------------------------------------
    counter #(
        .WIDTH(WIDTH)
    ) dut (
        .clk      (clk),
        .rst_n    (rst_n),
        .en       (en),
        .dir      (dir),
        .load_en  (load_en),
        .load_val (load_val),
        .count    (count),
        .overflow (overflow)
    );

    // -------------------------------------------------------------------------
    // Clock generation
    // -------------------------------------------------------------------------
    initial clk = 0;
    always #CLK_HALF clk = ~clk;

    // -------------------------------------------------------------------------
    // Waveform dumping — gated by +waves plusarg (LibreRun controlled)
    // -------------------------------------------------------------------------
    initial begin
        if ($test$plusargs("waves")) begin
            $dumpfile("waves.fst");
            $dumpvars(0, tb_counter);
            $display("[TB] Waveform dumping enabled -> waves.fst");
        end
    end

    // -------------------------------------------------------------------------
    // Main test sequencer
    // -------------------------------------------------------------------------
    initial begin
        errors = 0;

        // Read test name from plusarg
        if (!$value$plusargs("test=%s", test_name))
            test_name = "smoke";  // Default if no plusarg provided

        // Handle "default" alias
        if (test_name == "default")
            test_name = "smoke";

        // Read seed from plusarg
        if (!$value$plusargs("verilator+seed+%d", seed)) begin
            seed = $urandom();
        end

        $display("[TB] ================================================");
        $display("[TB] Test: %s", test_name);
        $display("[TB] Seed: %d", seed);
        $display("[TB] ================================================");

        void'($urandom(seed));  // Seed the RNG

        // Run appropriate test
        case (test_name)
            "smoke":      run_smoke_test();
            "basic":      run_basic_test();
            "wraparound": run_wraparound_test();
            "stress":     run_stress_test();
            "load":       run_load_test();
            "updown":     run_updown_test();
            default: begin
                $display("[FAIL] Unknown test: %s", test_name);
                errors++;
            end
        endcase

        // Final result
        $display("[TB] ================================================");
        if (errors == 0)
            $display("[PASS] Test '%s' completed successfully", test_name);
        else
            $display("[FAIL] Test '%s' failed with %0d error(s)", test_name, errors);
        $display("[TB] ================================================");

        $finish;
    end

    // -------------------------------------------------------------------------
    // Test: smoke
    // Quick sanity check - reset, count a few cycles, verify basic operation
    // -------------------------------------------------------------------------
    task run_smoke_test();
        int cycles;
        cycles = 30 + $urandom_range(0, 20);  // 30-50 cycles

        $display("[TB] Running smoke test for %0d cycles", cycles);

        // Initialize
        rst_n    = 0;
        en       = 0;
        dir      = 0;
        load_en  = 0;
        load_val = '0;

        // Reset
        repeat(3) @(posedge clk);
        @(negedge clk);
        rst_n = 1;

        // Check reset state
        @(negedge clk);
        if (count !== '0) begin
            $display("[FAIL] Count not 0 after reset (got %0d)", count);
            errors++;
        end

        // Enable counting
        en = 1;
        repeat(cycles) @(posedge clk);

        // Verify we counted
        @(negedge clk);
        if (count == 0) begin
            $display("[FAIL] Counter did not increment", count);
            errors++;
        end else begin
            $display("[TB] Counter reached %0d", count);
        end
    endtask

    // -------------------------------------------------------------------------
    // Test: basic
    // Full sequence: count, hold (en=0), resume, reset mid-count
    // -------------------------------------------------------------------------
    task run_basic_test();
        int cycles;
        logic [WIDTH-1:0] held_val;

        cycles = 80 + $urandom_range(0, 40);  // 80-120 cycles

        $display("[TB] Running basic test for ~%0d cycles", cycles);

        // Initialize and reset
        rst_n    = 0;
        en       = 0;
        dir      = 0;
        load_en  = 0;
        load_val = '0;

        repeat(3) @(posedge clk);
        rst_n = 1;
        @(negedge clk);

        // Count for a while
        en = 1;
        repeat(cycles/3) @(posedge clk);

        // Hold (disable enable)
        @(negedge clk);
        en = 0;
        held_val = count;
        $display("[TB] Holding count at %0d", held_val);

        repeat(5) @(posedge clk);
        @(negedge clk);
        if (count !== held_val) begin
            $display("[FAIL] Count changed while en=0 (was %0d, now %0d)", held_val, count);
            errors++;
        end

        // Resume counting
        en = 1;
        repeat(cycles/3) @(posedge clk);

        // Reset mid-count
        rst_n = 0;
        repeat(2) @(posedge clk);
        @(negedge clk);
        if (count !== '0) begin
            $display("[FAIL] Count not 0 after mid-run reset (got %0d)", count);
            errors++;
        end

        rst_n = 1;
        repeat(cycles/3) @(posedge clk);
    endtask

    // -------------------------------------------------------------------------
    // Test: wraparound
    // Count through full range, verify overflow flag
    // -------------------------------------------------------------------------
    task run_wraparound_test();
        int cycles;
        int max_val;
        logic saw_overflow;

        max_val = (2**WIDTH) - 1;
        cycles = max_val + 5 + $urandom_range(0, 10);  // Go past overflow

        $display("[TB] Running wraparound test for %0d cycles (max=%0d)", cycles, max_val);

        // Initialize and reset
        rst_n    = 0;
        en       = 0;
        dir      = 0;
        load_en  = 0;
        load_val = '0;

        repeat(3) @(posedge clk);
        rst_n = 1;
        @(negedge clk);

        // Count and watch for overflow
        en = 1;
        saw_overflow = 0;

        for (int i = 0; i < cycles; i++) begin
            @(posedge clk);
            @(negedge clk);
            if (overflow) begin
                $display("[TB] Overflow detected at cycle %0d, count=%0d", i, count);
                saw_overflow = 1;
            end
        end

        if (!saw_overflow) begin
            $display("[FAIL] No overflow detected during wraparound test");
            errors++;
        end

        // Verify count wrapped correctly
        if (count < 5) begin
            $display("[TB] Count wrapped correctly (now at %0d)", count);
        end else begin
            $display("[FAIL] Count did not wrap as expected (got %0d)", count);
            errors++;
        end
    endtask

    // -------------------------------------------------------------------------
    // Test: stress
    // Random enable toggling, random resets, verify count correctness
    // -------------------------------------------------------------------------
    task run_stress_test();
        int cycles;
        int expected_count;
        int reset_probability;

        cycles = 4000 + $urandom_range(0, 2000);  // 4000-6000 cycles
        reset_probability = 1;  // 1% chance of reset per cycle

        $display("[TB] Running stress test for %0d cycles", cycles);

        // Initialize
        rst_n        = 1;
        en           = 0;
        dir          = 0;
        load_en      = 0;
        load_val     = '0;
        expected_count = 0;

        // Initial reset
        rst_n = 0;
        repeat(3) @(posedge clk);
        rst_n = 1;
        @(negedge clk);

        // Random stimulus
        for (int i = 0; i < cycles; i++) begin
            // Random enable toggle (70% chance enabled)
            en = ($urandom_range(0, 99) < 70);

            // Random reset (1% chance)
            if ($urandom_range(0, 99) < reset_probability) begin
                rst_n = 0;
                expected_count = 0;
                @(posedge clk);
                rst_n = 1;
                $display("[TB] Random reset at cycle %0d", i);
            end else begin
                @(posedge clk);
            end

            // Update expected count
            @(negedge clk);
            if (rst_n && en) begin
                expected_count = (expected_count + 1) % (2**WIDTH);
            end

            // Periodic checking (every 100 cycles)
            if (i % 100 == 0 && rst_n) begin
                if (count !== expected_count[WIDTH-1:0]) begin
                    $display("[FAIL] Count mismatch at cycle %0d: expected=%0d, got=%0d",
                             i, expected_count[WIDTH-1:0], count);
                    errors++;
                end
            end
        end

        $display("[TB] Stress test completed %0d cycles", cycles);
    endtask

    // -------------------------------------------------------------------------
    // Test: load
    // Test load functionality with random values
    // -------------------------------------------------------------------------
    task run_load_test();
        int cycles;
        logic [WIDTH-1:0] load_value;

        cycles = 150 + $urandom_range(0, 100);  // 150-250 cycles

        $display("[TB] Running load test for %0d cycles", cycles);

        // Initialize and reset
        rst_n    = 0;
        en       = 0;
        dir      = 0;
        load_en  = 0;
        load_val = '0;

        repeat(3) @(posedge clk);
        rst_n = 1;
        @(negedge clk);

        // Perform random loads
        for (int i = 0; i < cycles; i++) begin
            if ($urandom_range(0, 9) < 2) begin  // 20% chance of load
                load_value = WIDTH'($urandom_range(0, (2**WIDTH)-1));
                load_en    = 1;
                load_val   = load_value;

                @(posedge clk);
                @(negedge clk);

                if (count !== load_value) begin
                    $display("[FAIL] Load failed: expected=%0d, got=%0d", load_value, count);
                    errors++;
                end else begin
                    $display("[TB] Loaded value %0d successfully", load_value);
                end

                load_en = 0;
            end else begin
                // Normal counting
                en = 1;
                @(posedge clk);
                @(negedge clk);
            end
        end
    endtask

    // -------------------------------------------------------------------------
    // Test: updown
    // Test up/down counting with random direction changes
    // -------------------------------------------------------------------------
    task run_updown_test();
        int cycles;
        int expected_count;

        cycles = 400 + $urandom_range(0, 200);  // 400-600 cycles

        $display("[TB] Running up/down test for %0d cycles", cycles);

        // Initialize and reset
        rst_n    = 0;
        en       = 1;
        dir      = 0;
        load_en  = 0;
        load_val = '0;

        repeat(3) @(posedge clk);
        rst_n = 1;
        expected_count = 0;
        @(negedge clk);

        // Random up/down counting
        for (int i = 0; i < cycles; i++) begin
            // Random direction change (10% chance)
            if ($urandom_range(0, 9) == 0) begin
                dir = ~dir;
                $display("[TB] Direction change at cycle %0d (dir=%0d)", i, dir);
            end

            @(posedge clk);
            @(negedge clk);

            // Update expected count
            if (dir)
                expected_count = (expected_count - 1) & ((2**WIDTH) - 1);
            else
                expected_count = (expected_count + 1) & ((2**WIDTH) - 1);

            // Periodic checking
            if (i % 50 == 0) begin
                if (count !== expected_count[WIDTH-1:0]) begin
                    $display("[FAIL] Count mismatch at cycle %0d: expected=%0d, got=%0d",
                             i, expected_count[WIDTH-1:0], count);
                    errors++;
                end
            end
        end

        $display("[TB] Up/down test completed %0d cycles", cycles);
    endtask

endmodule
